

import argparse

import runner

parser = argparse.ArgumentParser()
parser.add_argument("job", nargs="?", choices=["attributes", "articles"], default="attributes")
parser.add_argument("--limit", type=int, default=1)
parser.add_argument("--update", action="store_true")
args = parser.parse_args()

runner.run_job(args.job, args.limit, args.update)