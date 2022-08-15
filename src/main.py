import argparse
import json
import logging
from typing import Optional

from parser import load_data
from utils import add_generations, filter_relatives


def main(args) -> Optional[dict]:
    if not args.output:
        logging.basicConfig(level='ERROR')
    else:
        logging.basicConfig(level=args.log_level)

    logging.debug('Loading data')
    root = load_data(args.persons, args.families)
    if args.id:
        logging.debug(f'Filtering for {args.id}')
        root = filter_relatives(root, args.id)

    logging.debug('Adding generations')
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
parser.add_argument('--output', '-o', help='Path to output file')
parser.add_argument('--id', help='ID of a persons. Only this persons relatives will be added.')
parser.add_argument('--log-level', help='Logging level', default='DEBUG' if __debug__ else 'WARNING')

if __name__ == '__main__':
    result = main(parser.parse_args())
    if result:
        print(json.dumps(result))
