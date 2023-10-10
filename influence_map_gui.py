from itertools import combinations
import threading
from pyvis.network import Network
from json import JSONDecodeError
from colorama import Style
from colorama import Fore
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

window = None
global_text_output = ""

import PySimpleGUI as gui

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
def main(wndw, concept_list):
    global window
    window = wndw
    wiki_set = wikify_concepts(concept_list)
    connections_list = connect_concepts(wiki_set, wndw)
    graph_connections(connections_list, wiki_set)
    window.write_event_value("-FINISHED-", 0)


# clean up the connections and reduce the number for clarity and effectiveness
def clean(connections_list, min_connections=2):
    connections = list(connections_list)

    text_output(
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

    text_output(
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
    text_output(f'Wrote map to "{Fore.LIGHTCYAN_EX}{file_name}{Style.RESET_ALL}"')


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
def connect_concepts(wiki_set, wndw):
    connections_list = []
    wiki_set_values = tuple(wiki_set)
    seen_pages = set(wiki_set_values)
    important_words = get_important_words(seen_pages)
    try:
        prog_max = (
            (len(wiki_set_values) ** 2)
            * (DEFAULT_DEPTH_LIMIT**2)
            * DEFAULT_WIDTH_LIMIT
        )
        cur = 0
        wndw.write_event_value("-SET_PROGRESS_MAX-", prog_max)
        wndw.write_event_value("-SEARCHING-", 0)
        for page in wiki_set_values:
            for otherPage in wiki_set_values:

                def increment_progress():
                    nonlocal cur
                    cur += 1
                    wndw.write_event_value("-SET_PROGRESS-", cur)

                find_connections(
                    connections_list,
                    seen_pages,
                    page,
                    otherPage,
                    important_words,
                    increment_progress,
                )
    except KeyboardInterrupt:
        wndw.write_event_value("-POST_PROCESSING-", 0)
        connections_list = clean(connections_list, len(wiki_set_values))
        shallow_link_seen_pages(connections_list, wndw)
        return connections_list
    wndw.write_event_value("-POST_PROCESSING-", 0)
    connections_list = clean(connections_list, len(wiki_set_values))
    shallow_link_seen_pages(connections_list, wndw)
    return connections_list


# Builds a set of important terms from the target topics' summaries
def get_important_words(wiki_set):
    text_output("Generating set of key words...")
    important_words = set()
    for page in wiki_set:
        for word in page.summary.split() + page.title.split():
            if word.lower() not in STOP_WORD_SET:
                important_words.add(word.lower())
    return important_words


# Ranks the relevance of a wiki page based on the similarity of its
# summary terms to the summary terms of the target topics
def get_page_importance(wiki_page, important_words):
    text_output(
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
def shallow_link_seen_pages(found_connections, wndw):
    current_pages = set()
    for connection in found_connections:
        current_pages.add(connection.src)
        current_pages.add(connection.dest)
    text_output(
        f"Checking for additional cross-references between {Fore.LIGHTWHITE_EX}{len(current_pages)}{Style.RESET_ALL} pages..."
    )
    sleep_time = SLEEPER_DELAY * ((1 / len(current_pages)) ** (1 / 4))
    cur = 0
    wndw.write_event_value("-SET_PROGRESS_MAX-", len(current_pages) ** 2)
    for this_page in current_pages:
        sleep(sleep_time)
        page_links = get_page_links(this_page)
        for other_page in current_pages:
            if other_page != this_page and other_page in page_links:
                found_connections.append(create_edge(this_page, other_page))
            cur += 1
            wndw.write_event_value("-SET_PROGRESS-", cur)


# Gets the set of links from a given page
def get_page_links(page):
    page_links_gotten = False
    counter = 1
    while not page_links_gotten:
        try:
            page_links = set(page.links.values())
            page_links_gotten = True
        except JSONDecodeError:
            text_output(
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
    increment_progress,
    depth_limit=DEFAULT_DEPTH_LIMIT,
    width_limit=DEFAULT_WIDTH_LIMIT,
):
    if depth_limit == 0 and cur_page != target_page:
        increment_progress()
        return found_connections

    text_output(
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
                increment_progress,
                depth_limit - 1,
            )
            found_connections.append(create_edge(cur_page, sub_page))


# Builds an edge to connect the two related nodes for the given pages
def create_edge(src_page, dst_page, wght=1):
    edge = Edge(src_page, dst_page, wght)
    text_output(
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
                text_output(
                    f"Found wiki page for {Fore.LIGHTRED_EX}{concept}{Style.RESET_ALL} ({wiki_page.fullurl})."
                )
    return wiki_set


# Handles the command-line arguments
def handle_args(args):
    if len(args) < 1:
        bad_args_message()
        quit()
    if args[0] == "--help" or args[0] == "-h":
        print_help_message()
        quit()
    return handle_file(args)


# Handles the file input
def handle_file(args):
    delim = "\n"
    if len(args) > 1:
        delim = args[1]
    with open(args[0], "r") as inputFile:
        return inputFile.read().strip().split(delim)


# Displays the command help message
def print_help_message():
    text_output(
        f"To use, enter {sys.argv[0]} followed by the name of the file containing the names of concepts to investigate, separated by a delimineter value (default newline).".format(
            sys.argv
        )
    )


# Displays the error message for bad user input format
def bad_args_message():
    text_output(
        f"Please enter {sys.argv[0]} followed by a filename and (optionally) a delimineter value."
    )


# Displays the error message for bad user input format in gui
def bad_args_message_gui():
    text_output(
        f"Please either enter a filename containing a list or manually create a list.\n(All lists must have their entries separated by a delimineter value.)"
    )


# writes the given text to the PySimpleGUI window
def text_output(text):
    global window
    global global_text_output
    print(text)
    # filter out FORE and STYLE codes
    # determine if a color code is present
    # if so, set color to the color code
    if Fore.RED in text:
        color = Fore.RED
    elif Fore.LIGHTGREEN_EX in text:
        color = Fore.LIGHTGREEN_EX
    elif Fore.LIGHTCYAN_EX in text:
        color = Fore.LIGHTCYAN_EX
    elif Fore.LIGHTWHITE_EX in text:
        color = Fore.LIGHTWHITE_EX
    elif Fore.MAGENTA in text:
        color = Fore.MAGENTA
    elif Fore.LIGHTYELLOW_EX in text:
        color = Fore.LIGHTYELLOW_EX
    elif Fore.GREEN in text:
        color = Fore.GREEN
    elif Fore.LIGHTRED_EX in text:
        color = Fore.LIGHTRED_EX
    else:
        color = None
    # replace colors with quotes for emphasis
    if (
        "connections list" not in text
        and "Connections list" not in text
        and "cross-references" not in text
    ):
        text = re.sub(r"\x1b\[[0-9;]*m", '"', text)
    else:
        text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    if color is Fore.GREEN:
        text = "+ " + text
    elif color is Fore.LIGHTWHITE_EX:
        text = "> " + text
    elif color is Fore.LIGHTYELLOW_EX:
        text = "<= " + text
    global_text_output = tail(global_text_output, 9) + text + "\n"
    window.write_event_value("-OUTPUT-", 0)


# function to get last n lines of a string
def tail(string, n):
    return "\n".join(string.splitlines()[-n:]) + "\n"


# Calls main with the command-line args that the user passed
# if __name__ == "__main__":
#    main(handle_args(sys.argv[1:]))


# runner for the gui app
def gui_main():
    gui.theme("DarkBlack")

    layout = [
        # allow direct link bypass
        [
            gui.Column(
                [
                    [
                        gui.Checkbox(
                            "Allow direct link bypass",
                            key="allow_direct_link_bypass",
                            default=False,
                        )
                    ],
                    [
                        gui.Checkbox(
                            "Consolidate titles",
                            key="consolidate_titles",
                            default=True,
                        )
                    ],
                ]
            ),
            gui.Column(
                [
                    [gui.Text("Search intensity:")],
                    [gui.Text("Sleeper delay:")],
                    [gui.Text("Depth limit:")],
                    [gui.Text("Width limit:")],
                ]
            ),
            gui.Column(
                [
                    [
                        gui.InputText(
                            key="search_intensity",
                            default_text="5",
                            size=(5, 1),
                        )
                    ],
                    [
                        gui.InputText(
                            key="sleeper_delay",
                            default_text="1.5",
                            size=(5, 1),
                        )
                    ],
                    [
                        gui.InputText(
                            key="depth_limit",
                            default_text="3",
                            size=(5, 1),
                        )
                    ],
                    [
                        gui.InputText(
                            key="width_limit",
                            default_text="3",
                            size=(5, 1),
                        )
                    ],
                ]
            ),
            gui.Column(
                [
                    [gui.Text("Minimum connections override:")],
                    [gui.Text("Minimum connections multiplier:")],
                    [gui.Text("Summary threshold:")],
                ],
            ),
            gui.Column(
                [
                    [
                        gui.InputText(
                            key="min_connections_override",
                            default_text="-1",
                            size=(5, 1),
                        )
                    ],
                    [
                        gui.InputText(
                            key="min_connections_multiplier",
                            default_text="2",
                            size=(5, 1),
                        )
                    ],
                    [
                        gui.InputText(
                            key="summary_threshold",
                            default_text="20",
                            size=(5, 1),
                        )
                    ],
                ],
            ),
        ],
        # conceps to investigate ---
        [gui.Text("Enter a list of concepts to investigate:")],
        [gui.Multiline(key="input_text", size=(80, 10))],
        [
            gui.Text(
                "OR Enter the name of the file containing the concepts to investigate:"
            )
        ],
        [gui.InputText(key="input_file")],
        [gui.Text("Enter the delimineter value (default newline):")],
        [gui.InputText(key="delim")],
        [
            gui.Button("Execute Search"),
            gui.Button("Exit"),
        ],
        [gui.Text(key="output_text", size=(80, 10), text_color="light blue")],
        # progress bar
        [gui.Text(key="progress_text")],
        [
            gui.ProgressBar(
                100, orientation="h", size=(20, 20), expand_x=True, key="progress"
            )
        ],
    ]

    global window
    window = gui.Window("Concept Mapper", layout)

    while True:
        event, values = window.read()
        if event == gui.WIN_CLOSED or event == "Exit":
            break
        if event == "-OUTPUT-":
            color = values["-OUTPUT-"]
            window["output_text"].update(global_text_output)
        if event == "-SET_PROGRESS_MAX-":
            progress_value_max = int(values["-SET_PROGRESS_MAX-"])
            window["progress"].update(current_count=0, max=progress_value_max)
            window.refresh()
        if event == "-SET_PROGRESS-":
            progress_value = int(values["-SET_PROGRESS-"])
            window["progress"].update(current_count=progress_value)
            window.refresh()
        if event == "-SEARCHING-":
            window["progress_text"].update("Search Progress:")
        if event == "-POST_PROCESSING-":
            window["progress_text"].update("Post Processing...")
        if event == "-FINISHED-":
            window["progress_text"].update("Finished!")
        if event == "Execute Search":
            # set constants
            global ALLOW_DIRECT_LINK_BYPASS
            global CONSOLIDATE_TITLES
            global SEARCH_INTENSITY
            global SLEEPER_DELAY
            global DEPTH_LIMIT
            global WIDTH_LIMIT
            global MIN_CONNECTIONS_OVERRIDE
            global MIN_CONNECTIONS_MULTIPLIER
            global SUMMARY_THRESHOLD
            ALLOW_DIRECT_LINK_BYPASS = values["allow_direct_link_bypass"]
            CONSOLIDATE_TITLES = values["consolidate_titles"]
            SEARCH_INTENSITY = int(values["search_intensity"])
            SLEEPER_DELAY = float(values["sleeper_delay"])
            DEPTH_LIMIT = int(values["depth_limit"])
            WIDTH_LIMIT = int(values["width_limit"])
            MIN_CONNECTIONS_OVERRIDE = int(values["min_connections_override"])
            MIN_CONNECTIONS_MULTIPLIER = int(values["min_connections_multiplier"])
            SUMMARY_THRESHOLD = int(values["summary_threshold"])

            if values["input_file"] == "" and values["input_text"] == "":
                bad_args_message_gui()
            else:
                delim = "\n"
                if values["delim"] != "":
                    delim = values["delim"]
                if values["input_text"] != "":
                    concept_list = values["input_text"].strip().split(delim)
                if values["input_file"] != "":
                    concept_list = handle_file([values["input_file"], delim])
                threading.Thread(
                    target=main, args=(window, concept_list), daemon=True
                ).start()

    window.close()


if __name__ == "__main__":
    gui_main()
