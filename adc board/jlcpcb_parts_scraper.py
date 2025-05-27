import time
import csv
from playwright.sync_api import sync_playwright, TimeoutError


def get_jlcpcb_part_info(part_number: str, page) -> dict:
    """
    Fetches and extracts detailed information for a single JLCPCB part number
    using an existing Playwright page object.

    Args:
        part_number: The JLCPCB part number string.
        page: An active Playwright page object.

    Returns:
        A dictionary containing the part's information if found, otherwise a dictionary with error info.
    """
    url = f"https://jlcpcb.com/parts/componentSearch?searchTxt={part_number}"
    print(f"Fetching data for {part_number}...")

    try:
        # Navigate to the page and wait for the network to be idle
        page.goto(url, wait_until='networkidle', timeout=30000)

        # Execute JavaScript on the page to get the __NUXT__ object
        nuxt_data = page.evaluate("() => window.__NUXT__")

        if not nuxt_data:
            return {"JLCPCB Part #": part_number, "MFR Part #": "Error: Could not retrieve __NUXT__ data."}

        # Navigate the dictionary to find the part details
        part_list = nuxt_data.get('data', [{}])[0].get('tableInfo', {}).get('tableList', [])

        if not part_list:
            return {"JLCPCB Part #": part_number, "MFR Part #": "Error: Part not found in data."}

        part_details = part_list[0]

        # Extract the specific fields of interest
        return {
            "JLCPCB Part #": part_details.get("componentCode", part_number),
            "MFR Part #": part_details.get("componentModelEn"),
            "Manufacturer": part_details.get("componentBrandEn"),
            "Description": part_details.get("describe"),
            "Stock": part_details.get("stockCount"),
            "Package": part_details.get("componentSpecificationEn"),
            "Datasheet": part_details.get("dataManualUrl")
        }

    except TimeoutError:
        print(f"  -> Timeout error for {part_number}. Skipping.")
        return {"JLCPCB Part #": part_number, "MFR Part #": "Error: Page load timed out."}
    except Exception as e:
        print(f"  -> An unexpected error occurred for {part_number}: {e}")
        return {"JLCPCB Part #": part_number, "MFR Part #": f"Error: {e}"}


def main():
    """
    Main function to process a list of parts and save the results to a CSV file.
    """
    # The complete list of JLCPCB part numbers you provided
    part_numbers = [
        "C2152213", "C72134", "C107030", "C127965", "C2058017", "C25744", "C368442",
        "C25741", "C272875", "C14709", "C69932", "C1576", "C505479", "C2057542",
        "C307331", "C48346", "C52923", "C2060538", "C2901546", "C15850", "C25118",
        "C841384", "C77590", "C965555", "C76914", "C25905", "C190271", "C26083",
        "C521066", "C64982", "C1509602", "C98705", "C6549145", "C129363", "C5307756",
        "C45783", "C2901628", "C5644852", "C467192", "C185420", "C327228", "C401766",
        "C272377", "C2286", "C118987", "C161525", "C25079", "C1566", "C15127",
        "C2058582", "C7420370", "C339970", "C25796", "C77110", "C180439", "C270366",
        "C423184", "C22435967", "C82158", "C11702", "C1525", "C13564", "C162542",
        "C25091", "C17168", "C206499", "C25783", "C88880", "C116647"
    ]

    all_parts_data = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for part_num in part_numbers:
            part_info = get_jlcpcb_part_info(part_num, page)
            if part_info:
                all_parts_data.append(part_info)
            # A small delay to be respectful to the server
            time.sleep(0.5)

        browser.close()

    # Save the results to a CSV file
    if all_parts_data:
        output_filename = 'jlcpcb_parts_output.csv'
        # Use the keys from the first dictionary as headers
        headers = all_parts_data[0].keys()

        with open(output_filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writeheader()
            writer.writerows(all_parts_data)

        print(f"\n✅ Success! Data for {len(all_parts_data)} parts has been saved to '{output_filename}'")
    else:
        print("\n❌ No data was extracted.")


if __name__ == "__main__":
    main()