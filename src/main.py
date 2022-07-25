import argparse
import json
from typing import Optional

from parser import load_data
from utils import add_generations


def main(args) -> Optional[dict]:
    root = load_data(args.persons, args.families)
    add_generations(root)

    if args.output:
        with open(args.output, "w") as file:
            json.dump(root.dict(), file)
        return

    return root.dict(exclude_none=True, exclude_defaults=True)


parser = argparse.ArgumentParser(
    prog='CSV-GedcomX Converter',
    description='Converts two CSV files to one GedcomX file in JSON format')
parser.add_argument('persons', help='Path to CSV table containing the persons')
parser.add_argument('families', help='Path to CSV table containing the families')
parser.add_argument('--output', help='Path to output file')

if __name__ == '__main__':
    result = main(parser.parse_args())
    if result:
        print(json.dumps(result))
