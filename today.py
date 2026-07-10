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
import os
import time

import requests
from dateutil import relativedelta
from lxml import etree

# ---------------------------------------------------------------------------
# CONFIG — edit these
# ---------------------------------------------------------------------------
# Birth month, used for the live "Uptime" counter (day omitted by request).
BIRTHDAY = datetime.datetime(1995, 3, 1)
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
    """Returns time since birth in years and months, e.g. 'XX years, XX months'."""
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return "{} {}, {} {}".format(
        diff.years, "year" + format_plural(diff.years),
        diff.months, "month" + format_plural(diff.months))


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


def commit_getter(created_at):
    """Total commit contributions since the account was created.

    Sums contributionsCollection.totalCommitContributions year-by-year (the API
    caps each query at one year). Fast — a handful of queries — and it matches the
    commit count GitHub shows on the contribution graph.
    """
    start = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.datetime.now(datetime.timezone.utc)
    total = 0
    window = start
    while window < now:
        nxt = min(window + relativedelta.relativedelta(years=1), now)
        query_count("graph_commits")
        query = """
        query($from: DateTime!, $to: DateTime!, $login: String!) {
            user(login: $login) {
                contributionsCollection(from: $from, to: $to) {
                    totalCommitContributions
                    restrictedContributionsCount
                }
            }
        }"""
        variables = {"from": window.isoformat(), "to": nxt.isoformat(), "login": USER_NAME}
        cc = simple_request(commit_getter.__name__, query, variables).json()["data"]["user"]["contributionsCollection"]
        total += cc["totalCommitContributions"] + cc["restrictedContributionsCount"]
        window = nxt
    return total


# Values right-align to character column RC (must match build_header.py).
RC = 64


def _value_len(key):
    """justify_format length so a row's value right edge lands at column RC.

    Right edge = prefix + length + 2, with prefix = len('. ' + key + ':').
    So length = RC - prefix - 2 = RC - len(key) - 5.
    """
    return RC - len(key) - 5


def svg_overwrite(filename, age_data, commit_data, star_data, repo_data, contrib_data, follower_data):
    """Parses the SVG and rewrites the stat elements so every value hits column RC."""
    tree = etree.parse(filename)
    root = tree.getroot()
    justify_format(root, "age_data", age_data, _value_len("Uptime"))
    justify_format(root, "repo_data", repo_data, _value_len("Repos"))
    justify_format(root, "contrib_data", contrib_data, _value_len("Contributed"))
    justify_format(root, "star_data", star_data, _value_len("Stars"))
    justify_format(root, "commit_data", commit_data, _value_len("Commits"))
    justify_format(root, "follower_data", follower_data, _value_len("Followers"))
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

    commit_data, commit_time = perf_counter(commit_getter, acc_date)
    formatter("commit counter", commit_time)

    star_data, star_time = perf_counter(graph_repos_stars, "stars", ["OWNER"])
    formatter("star counter", star_time)

    repo_data, repo_time = perf_counter(graph_repos_stars, "repos", ["OWNER"])
    formatter("my repositories", repo_time)

    contrib_data, contrib_time = perf_counter(graph_repos_stars, "repos", ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"])
    formatter("contributed repos", contrib_time)

    follower_data, follower_time = perf_counter(follower_getter, USER_NAME)
    formatter("follower counter", follower_time)

    svg_overwrite(SVG_FILE, age_data, commit_data, star_data, repo_data, contrib_data, follower_data)

    print("Total GitHub GraphQL API calls:", "{:>3}".format(sum(QUERY_COUNT.values())))
