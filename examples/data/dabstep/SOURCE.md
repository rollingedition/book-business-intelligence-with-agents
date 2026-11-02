# Source: DABstep subset

A small subset of DABstep, the Data Agent Benchmark for Multi-step Reasoning, used in chapter 3 only.

- **Dataset:** `adyen/DABstep` on Hugging Face, https://huggingface.co/datasets/adyen/DABstep
- **Revision:** `1d740a52b8a41ba6fdd4d4435120a0429023dd24`, pinned because the repository takes new leaderboard uploads often
- **Paper:** *DABstep: Data Agent Benchmark for Multi-step Reasoning* (2025), https://arxiv.org/abs/2506.23719
- **Licence:** Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/. The dataset's own notice, with its title, copyright line and creators, is in `LICENSE` beside this file, copied byte for byte.
- **Fetched by:** `recordings/fetch_dabstep_subset.py`, which checks each file's SHA-256 at the revision above and writes this folder.

## Files taken

| File here | From | SHA-256 of the source file |
| --- | --- | --- |
| `LICENSE` | `LICENSE` | `f8a83b510da6dfffb2fab959cb8a48f05dec344e76338cff7cd5da36b50eec22` |
| `tasks.jsonl` | `data/tasks/dev.jsonl` | `c1da755a6fe9cb538fc84719f51e1db0bff0190a1d6905767ac18c755e66a07b` |
| `payments.csv.gz` | `data/context/payments.csv` | `5fbb26210a45427d7a6560cfab3a362a08e4067f27cd03695f211a51c47ffc25` |

## Changes

- `tasks.jsonl`: only the dev tasks 5, 49 and 70, the three easy tasks of the ten dev tasks with public answers. Each kept line is unchanged.
- `payments.csv.gz`: every one of the 138,236 rows, with the columns `ip_address`, `email_address`, `card_number` and `card_bin` removed. The first three are hashed identifiers of shoppers and cards, the fourth a card's bank identification number, and no task here needs them. The other 17 columns and every value are unchanged. Compressed with gzip.
- `LICENSE`: unchanged.
- Not taken: the other tasks, the fee and merchant files, `manual.md` and `payments-readme.md`. Chapter 3 links to the manual for its definition of fraud, "the ratio of fraudulent volume over total volume" (`data/context/manual.md`, section 7).

The merchant names in `payments.csv.gz` and in task 70 are kept as published. They are fictional businesses in DABstep's synthetic payments data; the dataset's `payments-readme.md` describes the table as a "Synthetic dataset of payment transactions".
