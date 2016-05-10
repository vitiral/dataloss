# dataloss: detecting data loss

This is a short python script who's purpose is to detect
both long running and instantanious data lass on a high
availibility system.

The idea is that you:
1. run this script on an external client, writing data to the system
2. do something to the system that might cause DU (data unavailable,
  i.e. a write error)
3. validate that the data written is correct

This script into account that data that has not been acknowledged
might be EITHER new or old data, therefore either is considered
valid.

Use Cntrl+C (SIGINT) to kill this program gracefully

# Usage
```
usage: dataloss.py [-h] [-l LOG] [-v] [--bs BS] [--blocks BLOCKS] [-a]
                   [--period PERIOD] [--timeout TIMEOUT]
                   [--total-blocks TOTAL_BLOCKS]
                   path

Run some IO and be able to detect and validate failure

positional arguments:
  path                  path to write-to or validate

optional arguments:
  -h, --help            show this help message and exit
  -l LOG, --log LOG     log to write or validate from
  -v, --validate        validate using logfile provided
  --bs BS               block size default=4096
  --blocks BLOCKS       num of blocks before wrapping
  -a, --auto-validate   if set, data will be validated while writting takes
                        place
  --period PERIOD       period between writes
  --timeout TIMEOUT     time in seconds to write
  --total-blocks TOTAL_BLOCKS
                        total number of blocks to write
```

Simple usage would just be:
```
python dataloss.py -a
```
This will push data, waiting for a failure and constantly validating data

validate the data with:
```
python dataloss.py -v 
```
