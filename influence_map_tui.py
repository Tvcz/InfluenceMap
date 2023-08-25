from itertools import combinations
from pyvis.network import Network
from json import JSONDecodeError
from colorama import Style
from colorama import Fore
from tqdm import tqdm
from time import sleep
from Edge import Edge
import wikipediaapi
import textwrap
import random
import nltk
import math
import sys
import re

nltk.download("stopwords")

STOP_WORD_SET = set(nltk.corpus.stopwords.words("english"))
ALLOW_DIRECT_LINK_BYPASS = False
SHOULD_CONSOLIDATE_TITLES = True
SEARCH_INTENSITY = 5
SLEEPER_DELAY = 1.5
DEFAULT_DEPTH_LIMIT = 3
DEFAULT_WIDTH_LIMIT = 3
MIN_CONNECTIONS_OVERRIDE = -1
MIN_CONNECTIONS_MULTIPLIER = 2
SUMMARY_THRESHOLD = 20
BLACKLIST_TITLES = [
    "Wayback Machine",
    "Digital object identifier",
    "International Standard Serial Number",
    "PubMed",
    "ISBN",
    "Système universitaire de documentation",
    "Semantic Scholar",
    "OCLC",
    "JSTOR",
    "Virtual International Authority File",
    "Trove",
]
BLACKLIST_TITLE_STARTERS = [
    "Category:",
    "Wikipedia:",
    "Help:",
    "Talk:",
    "Template:",
    "File:",
    "Portal:",
]

# runs all the top-level functions
def main(args):
    concept_list = handle_args(args)
    wiki_set = wikify_concepts(concept_list)
    connections_list = connect_concepts(wiki_set)
    graph_connections(connections_list, wiki_set)


# clean up the connections and reduce the number for clarity and effectiveness
def clean(connections_list, min_connections=2):
    connections = list(connections_list)
    print(
        f"Cleaning connections list {Fore.RED}({len(connections)}){Style.RESET_ALL}..."
    )

    # remove articles that don't have content
    connections = remove_blacklisted_title_starters(
        connections, BLACKLIST_TITLE_STARTERS
    )

    # remove cycles
    connections = remove_cycles(connections)

    # reduce dead-end connections
    connections = remove_dead_ends(
        connections, min_connections * MIN_CONNECTIONS_MULTIPLIER
    )

    # excluded titles
    connections = exclude_blacklisted_pages(connections, BLACKLIST_TITLES)

    # way too good at its job
    if SHOULD_CONSOLIDATE_TITLES:
        connections = consolidate_titles(connections)

    # remove cycles once more
    connections = remove_cycles(connections)

    # remove dead-end connections once more
    # connections = remove_dead_ends(connections, min_connections)

    print(
        f"Connections list clean {Fore.LIGHTGREEN_EX}({len(connections)}){Style.RESET_ALL}."
    )
    return connections


def remove_blacklisted_title_starters(connections, blacklist):
    filtered_connections = connections
    for word in blacklist:
        filtered_connections = [
            connection
            for connection in connections
            if not connection.either_title_startswith(word)
        ]
    return filtered_connections


def exclude_blacklisted_pages(connections, blacklist):
    blacklist = wikify_concepts(blacklist, False)
    blacklist_sums = set(
        [blacklisted_page.summary[:SUMMARY_THRESHOLD] for blacklisted_page in blacklist]
    )
    filtered_connections = [
        connection
        for connection in connections
        if not connection.either_summary_in(blacklist_sums, SUMMARY_THRESHOLD)
    ]
    return filtered_connections


# Remove connections which are not sufficiently connected to graph
def remove_dead_ends(connections, min_connections):
    min_connections = (
        min_connections if MIN_CONNECTIONS_OVERRIDE == -1 else MIN_CONNECTIONS_OVERRIDE
    )
    sources = [connection.src.title for connection in connections]
    targets = [connection.dest.title for connection in connections]
    connections = list(set(connections))
    connections = [
        connection
        for connection in connections
        if not (
            sources.count(connection.src.title) + targets.count(connection.src.title)
            < min_connections
        )
        and not (
            sources.count(connection.dest.title) + targets.count(connection.dest.title)
            < min_connections
        )
    ]
    return connections


def remove_cycles(connections):
    return [connection for connection in connections if not connection.is_cyclic()]


def consolidate_titles(connections):
    consolidated_connections = set()
    for edge, otherEdge in combinations(connections, 2):
        consolidated_connections.update(edge.consolidate(otherEdge))
    return list(consolidated_connections)


# Graph all the nodes on an html file
def graph_connections(connections_list, wiki_set):
    net = Network(height="750px", width="100%", bgcolor="#222222", font_color="white")
    concepts = set([page.title for page in wiki_set])
    for connection in connections_list:
        src_title = connection.src.title
        src_sum = shorten_summary(connection.src.summary)
        src_color = "#937ef2" if src_title in concepts else "#7eacf2"
        trgt_title = connection.dest.title
        trgt_sum = shorten_summary(connection.dest.summary)
        trgt_color = "#937ef2" if trgt_title in concepts else "#7eacf2"
        net.add_node(src_title, color=src_color)
        net.add_node(trgt_title, color=trgt_color)
        net.add_edge(src_title, trgt_title)
        net.get_node(src_title)["title"] = textwrap.fill(src_sum, 75)
        net.get_node(trgt_title)["title"] = textwrap.fill(trgt_sum, 75)
    file_name = get_file_name(concepts)
    net.show(file_name)
    print(f'Wrote map to "{Fore.LIGHTCYAN_EX}{file_name}{Style.RESET_ALL}"')


# Create file name for output based on input args
def get_file_name(concepts):
    concept_list = list(concepts)
    if len(concept_list) == 0:
        return "influence_map.html"
    elif len(concept_list) == 1:
        return "influence_map({0}).html".format(concept_list[0])
    elif len(concept_list) == 2:
        return "influence_map({0},{1}).html".format(*concept_list)
    elif len(concept_list) == 3:
        return "influence_map({0},{1},{2}).html".format(*concept_list)
    else:
        return "influence_map({0},{1},{2}...).html".format(*concept_list[:3])


# Simplify a wiki article summary (buggy, eh...)
def shorten_summary(summary):
    summary = "".join(re.split("\(|\)|\[|\]", summary)[::2])
    if len(summary) > 100:
        return summary.partition(".")[0] + "."
    return summary


# Start up the connection recursion and handle setup and cleanup of connections
def connect_concepts(wiki_set):
    connections_list = []
    wiki_set_values = tuple(wiki_set)
    seen_pages = set(wiki_set_values)
    important_words = get_important_words(seen_pages)
    try:
        with tqdm(total=len(wiki_set_values) ** 2) as progress_bar:  # WRONG
            for page in wiki_set_values:
                for otherPage in wiki_set_values:
                    find_connections(
                        connections_list,
                        seen_pages,
                        page,
                        otherPage,
                        important_words,
                        progress_bar,
                    )
                    progress_bar.update(1)
    except KeyboardInterrupt:
        connections_list = clean(connections_list, len(wiki_set_values))
        shallow_link_seen_pages(connections_list)
        return connections_list
    connections_list = clean(connections_list, len(wiki_set_values))
    shallow_link_seen_pages(connections_list)
    return connections_list


# Builds a set of important terms from the target topics' summaries
def get_important_words(wiki_set):
    print("Generating set of key words...")
    important_words = set()
    for page in wiki_set:
        for word in page.summary.split() + page.title.split():
            if word.lower() not in STOP_WORD_SET:
                important_words.add(word.lower())
    return important_words


# Ranks the relevance of a wiki page based on the similarity of its
# summary terms to the summary terms of the target topics
def get_page_importance(wiki_page, important_words):
    print(
        f"Analyzing importance of {Fore.LIGHTWHITE_EX}{wiki_page.title}{Style.RESET_ALL}..."
    )
    importantness = 0
    for word in wiki_page.summary.split():
        word_lower = word.lower()
        if word_lower not in STOP_WORD_SET:
            if word_lower in important_words:
                importantness += 1
    return importantness


# Connect up any nodes whose pages reference each other
def shallow_link_seen_pages(found_connections):
    current_pages = set()
    for connection in found_connections:
        current_pages.add(connection.src)
        current_pages.add(connection.dest)
    print(
        f"Checking for additional cross-references between {Fore.LIGHTWHITE_EX}{len(current_pages)}{Style.RESET_ALL} pages..."
    )
    sleep_time = SLEEPER_DELAY * ((1 / len(current_pages)) ** (1 / 4))
    for this_page in current_pages:
        sleep(sleep_time)
        page_links = get_page_links(this_page)
        for other_page in current_pages:
            if other_page != this_page and other_page in page_links:
                found_connections.append(create_edge(this_page, other_page))


# Gets the set of links from a given page
def get_page_links(page):
    page_links_gotten = False
    counter = 1
    while not page_links_gotten:
        try:
            page_links = set(page.links.values())
            page_links_gotten = True
        except JSONDecodeError:
            print(
                f"{Fore.MAGENTA}Being throttled, backing off ({counter})...{Style.RESET_ALL}"
            )
            sleep(SLEEPER_DELAY * (math.e**counter))
        finally:
            counter += 1
    return page_links


# Searches for a connection between cur_page and target_page
def find_connections(
    found_connections,
    seen_pages,
    cur_page,
    target_page,
    important_words,
    progress_bar,
    depth_limit=DEFAULT_DEPTH_LIMIT,
    width_limit=DEFAULT_WIDTH_LIMIT,
):
    if depth_limit == 0 and cur_page != target_page:
        return found_connections

    print(
        f"Looking for connections between {Fore.LIGHTYELLOW_EX}{cur_page.title}{Style.RESET_ALL} and {Fore.LIGHTYELLOW_EX}{target_page.title}{Style.RESET_ALL}."
    )
    sleep(SLEEPER_DELAY)

    cur_page_links = cur_page.links

    # Connect new pages to exisiting nodes
    linked_pages = list(cur_page_links.values())
    for this_page in linked_pages:
        if this_page in seen_pages:
            found_connections.append(create_edge(cur_page, this_page))

    seen_pages.update(linked_pages)

    # Connection found, great
    if ALLOW_DIRECT_LINK_BYPASS and target_page.title in cur_page_links.keys():
        found_connections.append(create_edge(cur_page, target_page, 1))
    # No connection found in immediate vicinity
    else:
        # Finds articles that have similar topics mentioned in the summary and selects the best number allowed by
        # width_limit, from a random sample determined by the SEARCH_INTENSITY
        if len(linked_pages) > width_limit * SEARCH_INTENSITY:
            linked_pages = random.sample(linked_pages, width_limit * SEARCH_INTENSITY)
            linked_pages.sort(
                key=lambda page: get_page_importance(page, important_words),
                reverse=True,
            )
            linked_pages = linked_pages[:width_limit]
        # Articles with a number of links between width_limit and width_limit * SEARCH_INTENSITY.
        # I arbitrarily chose to choose links completely randomly in this case.
        if len(linked_pages) > width_limit:
            linked_pages = random.sample(linked_pages, width_limit)
        # Searches through the links allowanced to linked_pages
        for sub_page in linked_pages:
            find_connections(
                found_connections,
                seen_pages,
                sub_page,
                target_page,
                important_words,
                progress_bar,
                depth_limit - 1,
            )
            found_connections.append(create_edge(cur_page, sub_page))


# Builds an edge to connect the two related nodes for the given pages
def create_edge(src_page, dst_page, wght=1):
    edge = Edge(src_page, dst_page, wght)
    print(
        f"Added {Fore.GREEN}{src_page.title}{Style.RESET_ALL} -> {Fore.GREEN}{dst_page.title}{Style.RESET_ALL}."
    )
    return edge


# Gets the relevant wiki articles for a list of concepts
def wikify_concepts(concept_list, verbose=True):
    wiki = wikipediaapi.Wikipedia("en")
    wiki_set = set()
    for concept in concept_list:
        wiki_page = wiki.page(concept)
        if wiki_page.exists():
            wiki_set.add(wiki_page)
            if verbose:
                print(
                    f"Found wiki page for {Fore.LIGHTRED_EX}{concept}{Style.RESET_ALL} ({wiki_page.fullurl})."
                )
    return wiki_set


# Handles the command-line arguments
def handle_args(args):
    if len(args) < 1:
        bad_args_message()
    if args[0] == "--help" or args[0] == "-h":
        print_help_message()
        quit()
    delim = "\n"
    if len(args) > 1:
        delim = args[1]
    with open(args[0], "r") as inputFile:
        return inputFile.read().split(delim)


# Displays the command help message
def print_help_message():
    print(
        f"To use, enter {sys.argv[0]} followed by the name of the file containing the names of concepts to investigate, separated by a delimineter value (default newline).".format(
            sys.argv
        )
    )


# Displays the error message for bad user input format
def bad_args_message():
    print(
        f"{Fore.RED}Please enter {sys.argv[0]} followed by a filename and (optionally) a delimineter value.{Style.RESET_ALL}"
    )
    exit()


# Calls main with the command-line args that the user passed
if __name__ == "__main__":
    main(sys.argv[1:])
