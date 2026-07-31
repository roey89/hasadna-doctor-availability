import subprocess
import sys
import prepare_data
import os


def run_command(command):    
    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, check=True, text=True, capture_output=True, encoding='utf-8')
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

def run_full_pipeline():
    try:
        # # python clalit_crawl.py --dry-run
        # run_command(["python", "clalit_crawl.py", "--dry-run"])

        # # python clalit_crawl.py --specs 58 --cities "תל אביב יפו"
        # run_command(["python", "clalit_crawl.py", "--specs", "58", "--cities", "תל אביב יפו"])

        # # python dump_cities.py
        # run_command(["python", "dump_cities.py"])

        # # python run_parallel.py --setup --workers 10
        # run_command(["python", "run_parallel.py", "--setup", "--workers", "10"])

        # # python run_parallel.py --workers 10 --cities-file data/cities.txt
        # run_command(["python", "run_parallel.py", "--workers", "10", "--cities-file", "data/cities.txt"])

        # # python run_parallel.py --merge --workers 10
        # run_command(["python", "run_parallel.py", "--merge", "--workers", "10"])

        run_command(["python", "maccabi_scraper.py"])

        data = prepare_data.open_and_clean_all(
            "data/raw/clalit/parallel",
            "data/raw/maccabi/maccabi_full_data_with_appointments.json",
        )

        data.to_csv("data/clean/merged.csv", index=False)
        data[data["kupah"] == "maccabi"].to_csv("data/clean/maccabi.csv", index=False)
        data[data["kupah"] == "clalit"].to_csv("data/clean/clalit.csv", index=False)

        run_command(["python", "process_data.py"])
        run_command(["python", "grid_creation.py"])
        run_command(["python", "visualize_map.py"])

        print("Full pipeline executed successfully.")

    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {' '.join(e.cmd)}", file=sys.stderr)
        print(f"Return code: {e.returncode}", file=sys.stderr)
        print(f"Output: {e.stdout}", file=sys.stderr)
        print(f"Error output: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Error: Command not found - {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run_full_pipeline()
