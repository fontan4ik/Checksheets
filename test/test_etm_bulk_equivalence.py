import sys

sys.path.insert(0, "/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets")

from etm_sync_multi_store import (
    add_stock_to_lookup,
    resolve_stock,
    resolve_gds_code,
    resolve_stock_loose,
    resolve_gds_code_loose,
)


def run_case(article, gds, rem):
    lookup = {}
    gds_lookup = {}
    tails = {}
    article_to_gds = {}
    tail_to_gds = {}
    loose_entries = []
    add_stock_to_lookup(
        lookup,
        gds_lookup,
        tails,
        article_to_gds,
        tail_to_gds,
        loose_entries,
        {"GdsCode": gds, "Article": article, "RemInfo": rem},
    )
    return {
        "lookup": lookup,
        "gds_lookup": gds_lookup,
        "tails": tails,
        "article_to_gds": article_to_gds,
        "tail_to_gds": tail_to_gds,
        "loose_entries": loose_entries,
    }


def main():
    case = run_case("33126.100", "5394861", "8")
    assert case["lookup"]["33126100"] == 8
    assert case["lookup"]["33126"] == 8
    assert resolve_stock("33126", case["lookup"], case["tails"]) == 8
    assert resolve_gds_code("33126", case["article_to_gds"], case["tail_to_gds"]) == "5394861"

    suffixed = run_case("2850645A", "2850645", "11")
    assert resolve_stock_loose("2850645", suffixed["loose_entries"]) == 11
    assert resolve_gds_code_loose("2850645", suffixed["loose_entries"]) == "2850645"

    zeros = run_case("K_PR5_LED_100", "777", "4")
    assert resolve_stock_loose("K_PR5_LED_10", zeros["loose_entries"]) == 4
    assert resolve_gds_code_loose("K_PR5_LED_10", zeros["loose_entries"]) == "777"

    infix = run_case("DA12-32-30-bas", "595716", "13")
    assert resolve_stock_loose("23230", infix["loose_entries"]) == 0
    assert resolve_gds_code_loose("23230", infix["loose_entries"]) == ""

    numeric_extension = run_case("332169", "888", "6")
    assert resolve_stock_loose("33216", numeric_extension["loose_entries"]) == 0
    assert resolve_gds_code_loose("33216", numeric_extension["loose_entries"]) == ""

    formatted_numeric = run_case("02-0007-0021", "999", "12")
    assert resolve_stock_loose("020007", formatted_numeric["loose_entries"]) == 0
    assert resolve_gds_code_loose("020007", formatted_numeric["loose_entries"]) == ""

    mixed_tail = run_case("LkecLED25wA65E2765", "6528611", "80")
    assert resolve_stock("LkecLED7.5wGL45E2765", mixed_tail["lookup"], mixed_tail["tails"]) == 0
    assert resolve_gds_code("LkecLED7.5wGL45E2765", mixed_tail["article_to_gds"], mixed_tail["tail_to_gds"]) == ""

    numeric_tail = run_case("22068", "123", "261")
    assert resolve_stock("22068", numeric_tail["lookup"], numeric_tail["tails"]) == 261
    assert resolve_gds_code("22068", numeric_tail["article_to_gds"], numeric_tail["tail_to_gds"]) == "123"

    print("bulk equivalence tests passed")


if __name__ == "__main__":
    main()
