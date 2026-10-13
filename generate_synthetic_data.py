"""
generate_synthetic_data.py

Command-line way to (re)generate demo data in the configured MongoDB
(MONGODB_URI in .env -> Atlas, or any other Mongo).

    python generate_synthetic_data.py                 # 100 students, 3 groups
    python generate_synthetic_data.py --count 200
    python generate_synthetic_data.py --reset         # remove old demo data first
    python generate_synthetic_data.py --purge         # only remove demo data

Only data tagged source="synthetic" is ever touched - groups and students
created manually or imported from Excel are never modified or deleted.
(The same actions are available as buttons in the admin web interface.)
"""

import argparse
import json

from data_access.mongo_repository import MongoAcademicRepository
from data_pipeline.synthetic_seed import seed_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic demo data in MongoDB.")
    parser.add_argument("--count", type=int, default=100, help="number of students (default 100)")
    parser.add_argument("--reset", action="store_true", help="remove old synthetic data first")
    parser.add_argument("--purge", action="store_true", help="only remove synthetic data")
    args = parser.parse_args()

    repository = MongoAcademicRepository()

    if args.purge:
        print(json.dumps(repository.purge_synthetic(), indent=2))
        return

    result = seed_database(repository, args.count, reset=args.reset)
    print(json.dumps(result, indent=2, default=str))
    print(json.dumps(repository.stats(), indent=2))


if __name__ == "__main__":
    main()
