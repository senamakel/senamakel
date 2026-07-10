#!/usr/bin/env python3
"""
Dynamic GitHub profile header generator.

Fetches live GitHub statistics via the GraphQL v4 API and writes them into the
element ids inside `header.svg` (a neofetch-style terminal card). Meant to be
run on a schedule by the GitHub Action in .github/workflows/main.yml.

Adapted from Andrew Grant's (Andrew6rant) profile generator.

Required environment variables:
  ACCESS_TOKEN  Fine-grained PAT with read access to followers, starring,
                metadata, contents and commit statuses across all repositories.
  USER_NAME     GitHub login to generate stats for (e.g. 'senamakel').
"""
import datetime
import hashlib
import os
import time

import requests
from dateutil import relativedelta
from lxml import etree

# ---------------------------------------------------------------------------
# CONFIG — edit these
# ---------------------------------------------------------------------------
# Your birthday, used for the live "Uptime" counter. Format: (year, month, day).
# TODO: set your real birthday here.
BIRTHDAY = datetime.datetime(1990, 1, 1)
SVG_FILE = "header.svg"
# ---------------------------------------------------------------------------

HEADERS = {"authorization": "token " + os.environ["ACCESS_TOKEN"]}
USER_NAME = os.environ["USER_NAME"]
QUERY_COUNT = {
    "user_getter": 0, "follower_getter": 0, "graph_repos_stars": 0,
    "recursive_loc": 0, "graph_commits": 0, "loc_query": 0,
}
OWNER_ID = None


def daily_readme(birthday):
    """Returns time since birth, e.g. 'XX years, XX months, XX days'."""
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return "{} {}, {} {}, {} {}{}".format(
        diff.years, "year" + format_plural(diff.years),
        diff.months, "month" + format_plural(diff.months),
        diff.days, "day" + format_plural(diff.days),
        " 🎂" if (diff.months == 0 and diff.days == 0) else "")


def format_plural(unit):
    return "s" if unit != 1 else ""


def query_count(funct_id):
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1


def simple_request(func_name, query, variables):
    request = requests.post("https://api.github.com/graphql",
                            json={"query": query, "variables": variables}, headers=HEADERS)
    if request.status_code == 200:
        return request
    raise Exception(func_name, "has failed with a", request.status_code, request.text, QUERY_COUNT)


def user_getter(username):
    """Returns the account id and creation time of the user."""
    query_count("user_getter")
    query = """
    query($login: String!){
        user(login: $login) { id createdAt }
    }"""
    request = simple_request(user_getter.__name__, query, {"login": username})
    return {"id": request.json()["data"]["user"]["id"]}, request.json()["data"]["user"]["createdAt"]


def follower_getter(username):
    query_count("follower_getter")
    query = """
    query($login: String!){
        user(login: $login) { followers { totalCount } }
    }"""
    request = simple_request(follower_getter.__name__, query, {"login": username})
    return int(request.json()["data"]["user"]["followers"]["totalCount"])


def graph_commits(start_date, end_date):
    query_count("graph_commits")
    query = """
    query($start_date: DateTime!, $end_date: DateTime!, $login: String!) {
        user(login: $login) {
            contributionsCollection(from: $start_date, to: $end_date) {
                contributionCalendar { totalContributions }
            }
        }
    }"""
    variables = {"start_date": start_date, "end_date": end_date, "login": USER_NAME}
    request = simple_request(graph_commits.__name__, query, variables)
    return int(request.json()["data"]["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"])


def graph_repos_stars(count_type, owner_affiliation, cursor=None):
    """Returns total repository or star count."""
    query_count("graph_repos_stars")
    query = """
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges { node { ... on Repository { nameWithOwner stargazers { totalCount } } } }
                pageInfo { endCursor hasNextPage }
            }
        }
    }"""
    variables = {"owner_affiliation": owner_affiliation, "login": USER_NAME, "cursor": cursor}
    request = simple_request(graph_repos_stars.__name__, query, variables)
    if count_type == "repos":
        return request.json()["data"]["user"]["repositories"]["totalCount"]
    if count_type == "stars":
        return stars_counter(request.json()["data"]["user"]["repositories"]["edges"])


def stars_counter(data):
    return sum(node["node"]["stargazers"]["totalCount"] for node in data)


def recursive_loc(owner, repo_name, data, cache_comment, addition_total=0, deletion_total=0, my_commits=0, cursor=None):
    """Pages through a repository's commit history to tally my added/deleted LOC."""
    query_count("recursive_loc")
    query = """
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) {
            defaultBranchRef { target { ... on Commit {
                history(first: 100, after: $cursor) {
                    totalCount
                    edges { node { ... on Commit {
                        committedDate } author { user { id } } deletions additions } }
                    pageInfo { endCursor hasNextPage }
                }
            } } }
        }
    }"""
    variables = {"repo_name": repo_name, "owner": owner, "cursor": cursor}
    request = requests.post("https://api.github.com/graphql",
                            json={"query": query, "variables": variables}, headers=HEADERS)
    if request.status_code == 200:
        if request.json()["data"]["repository"]["defaultBranchRef"] is not None:
            return loc_counter_one_repo(owner, repo_name, data, cache_comment,
                                        request.json()["data"]["repository"]["defaultBranchRef"]["target"]["history"],
                                        addition_total, deletion_total, my_commits)
        return 0
    force_close_file(data, cache_comment)
    if request.status_code == 403:
        raise Exception("Too many requests in a short amount of time! Hit the anti-abuse limit.")
    raise Exception("recursive_loc() failed", request.status_code, request.text, QUERY_COUNT)


def loc_counter_one_repo(owner, repo_name, data, cache_comment, history, addition_total, deletion_total, my_commits):
    for node in history["edges"]:
        if node["node"]["author"]["user"] == OWNER_ID:
            my_commits += 1
            addition_total += node["node"]["additions"]
            deletion_total += node["node"]["deletions"]
    if history["edges"] == [] or not history["pageInfo"]["hasNextPage"]:
        return addition_total, deletion_total, my_commits
    return recursive_loc(owner, repo_name, data, cache_comment, addition_total, deletion_total,
                         my_commits, history["pageInfo"]["endCursor"])


def loc_query(owner_affiliation, comment_size=0, force_cache=False, cursor=None, edges=None):
    """Queries every accessible repo, then hands off to the cache builder."""
    query_count("loc_query")
    edges = edges if edges is not None else []
    query = """
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
                edges { node { ... on Repository {
                    nameWithOwner
                    defaultBranchRef { target { ... on Commit { history { totalCount } } } }
                } } }
                pageInfo { endCursor hasNextPage }
            }
        }
    }"""
    variables = {"owner_affiliation": owner_affiliation, "login": USER_NAME, "cursor": cursor}
    request = simple_request(loc_query.__name__, query, variables)
    page = request.json()["data"]["user"]["repositories"]
    if page["pageInfo"]["hasNextPage"]:
        return loc_query(owner_affiliation, comment_size, force_cache, page["pageInfo"]["endCursor"], edges + page["edges"])
    return cache_builder(edges + page["edges"], comment_size, force_cache)


def cache_builder(edges, comment_size, force_cache, loc_add=0, loc_del=0):
    """Uses a per-user cache file so only repos with new commits are re-scanned."""
    os.makedirs("cache", exist_ok=True)
    cached = True
    filename = "cache/" + hashlib.sha256(USER_NAME.encode("utf-8")).hexdigest() + ".txt"
    try:
        with open(filename, "r") as f:
            data = f.readlines()
    except FileNotFoundError:
        data = ["This line is a comment block. Write whatever you want here.\n"] * comment_size
        with open(filename, "w") as f:
            f.writelines(data)

    if len(data) - comment_size != len(edges) or force_cache:
        cached = False
        flush_cache(edges, filename, comment_size)
        with open(filename, "r") as f:
            data = f.readlines()

    cache_comment = data[:comment_size]
    data = data[comment_size:]
    for index in range(len(edges)):
        repo_hash, commit_count, *__ = data[index].split()
        if repo_hash == hashlib.sha256(edges[index]["node"]["nameWithOwner"].encode("utf-8")).hexdigest():
            try:
                if int(commit_count) != edges[index]["node"]["defaultBranchRef"]["target"]["history"]["totalCount"]:
                    owner, repo_name = edges[index]["node"]["nameWithOwner"].split("/")
                    loc = recursive_loc(owner, repo_name, data, cache_comment)
                    data[index] = repo_hash + " " + str(edges[index]["node"]["defaultBranchRef"]["target"]["history"]["totalCount"]) + " " + str(loc[2]) + " " + str(loc[0]) + " " + str(loc[1]) + "\n"
            except TypeError:  # empty repo
                data[index] = repo_hash + " 0 0 0 0\n"
    with open(filename, "w") as f:
        f.writelines(cache_comment)
        f.writelines(data)
    for line in data:
        loc = line.split()
        loc_add += int(loc[3])
        loc_del += int(loc[4])
    return [loc_add, loc_del, loc_add - loc_del, cached]


def flush_cache(edges, filename, comment_size):
    with open(filename, "r") as f:
        data = f.readlines()[:comment_size] if comment_size else []
    with open(filename, "w") as f:
        f.writelines(data)
        for node in edges:
            f.write(hashlib.sha256(node["node"]["nameWithOwner"].encode("utf-8")).hexdigest() + " 0 0 0 0\n")


def force_close_file(data, cache_comment):
    filename = "cache/" + hashlib.sha256(USER_NAME.encode("utf-8")).hexdigest() + ".txt"
    with open(filename, "w") as f:
        f.writelines(cache_comment)
        f.writelines(data)
    print("Partial cache data saved to", filename)


def commit_counter(comment_size):
    """Sums my commits across all repos, using the cache built by cache_builder."""
    filename = "cache/" + hashlib.sha256(USER_NAME.encode("utf-8")).hexdigest() + ".txt"
    with open(filename, "r") as f:
        data = f.readlines()[comment_size:]
    return sum(int(line.split()[2]) for line in data)


# Values right-align to character column RC (must match build_header.py).
RC = 56


def _value_len(key):
    """justify_format length so a row's value right edge lands at column RC.

    Right edge = prefix + length + 2, with prefix = len('. ' + key + ':').
    So length = RC - prefix - 2 = RC - len(key) - 5.
    """
    return RC - len(key) - 5


def svg_overwrite(filename, age_data, commit_data, star_data, repo_data, contrib_data, follower_data, loc_data):
    """Parses the SVG and rewrites the stat elements so every value hits column RC."""
    tree = etree.parse(filename)
    root = tree.getroot()
    justify_format(root, "age_data", age_data, _value_len("Uptime"))
    justify_format(root, "repo_data", repo_data, _value_len("Repos"))
    justify_format(root, "contrib_data", contrib_data, _value_len("Contributed"))
    justify_format(root, "star_data", star_data, _value_len("Stars"))
    justify_format(root, "commit_data", commit_data, _value_len("Commits"))
    justify_format(root, "follower_data", follower_data, _value_len("Followers"))
    # Lines of Code: total right-aligns to RC; colored diff sits inline before the leader.
    loc_add, loc_del, loc_total = str(loc_data[0]), str(loc_data[1]), str(loc_data[2])
    find_and_replace(root, "loc_add", loc_add)
    find_and_replace(root, "loc_del", loc_del)
    find_and_replace(root, "loc_data", loc_total)
    # fixed chars on the line: '. Lines of Code:' (16) + ' ( ' + '++' + ', ' + '--' + ' )' = 27
    dots_len = RC - 27 - len(loc_add) - len(loc_del) - len(loc_total)
    if dots_len <= 2:
        loc_dots = {0: "", 1: " ", 2: ". "}.get(max(0, dots_len), " ")
    else:
        loc_dots = " " + ("." * (dots_len - 2)) + " "
    find_and_replace(root, "loc_data_dots", loc_dots)
    tree.write(filename, encoding="utf-8", xml_declaration=True)


def justify_format(root, element_id, new_text, length=0):
    """Sets the element text and pads the sibling `_dots` element to justify it."""
    if isinstance(new_text, int):
        new_text = "{:,}".format(new_text)
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)
    just_len = max(0, length - len(new_text))
    if just_len <= 2:
        dot_string = {0: "", 1: " ", 2: ". "}[just_len]
    else:
        dot_string = " " + ("." * just_len) + " "
    find_and_replace(root, element_id + "_dots", dot_string)


def find_and_replace(root, element_id, new_text):
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text


def perf_counter(funct, *args):
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start


def formatter(query_type, difference):
    print("{:<23}".format("   " + query_type + ":"), end="")
    unit = " s " if difference > 1 else " ms"
    val = difference if difference > 1 else difference * 1000
    print("{:>12}".format("%.4f" % val + unit))


if __name__ == "__main__":
    print("Calculation times:")
    user_data, user_time = perf_counter(user_getter, USER_NAME)
    OWNER_ID, acc_date = user_data
    formatter("account data", user_time)

    age_data, age_time = perf_counter(daily_readme, BIRTHDAY)
    formatter("age calculation", age_time)

    total_loc, loc_time = perf_counter(loc_query, ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"], 7)
    formatter("LOC (cached)" if total_loc[-1] else "LOC (no cache)", loc_time)

    commit_data, commit_time = perf_counter(commit_counter, 7)
    formatter("commit counter", commit_time)

    star_data, star_time = perf_counter(graph_repos_stars, "stars", ["OWNER"])
    formatter("star counter", star_time)

    repo_data, repo_time = perf_counter(graph_repos_stars, "repos", ["OWNER"])
    formatter("my repositories", repo_time)

    contrib_data, contrib_time = perf_counter(graph_repos_stars, "repos", ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"])
    formatter("contributed repos", contrib_time)

    follower_data, follower_time = perf_counter(follower_getter, USER_NAME)
    formatter("follower counter", follower_time)

    formatted_loc = ["{:,}".format(total_loc[0]), "{:,}".format(total_loc[1]), "{:,}".format(total_loc[2])]
    svg_overwrite(SVG_FILE, age_data, commit_data, star_data, repo_data, contrib_data, follower_data, formatted_loc)

    print("Total GitHub GraphQL API calls:", "{:>3}".format(sum(QUERY_COUNT.values())))
