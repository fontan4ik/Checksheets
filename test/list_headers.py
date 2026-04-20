import gsheets_utils
import config

def main():
    try:
        ws = gsheets_utils.get_worksheet("ТЕСТ")
        headers = ws.row_values(1)
        for i, h in enumerate(headers):
            print(f"Col {i+1} ({chr(65+i) if i < 26 else chr(64+i//26)+chr(65+i%26)}): {h}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
