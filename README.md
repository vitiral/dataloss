# dataloss: detecting data loss

This is a short python script who's purpose is to detect
both long running and instantanious data lass on a high
availibility system.

The idea is that you:
- run this script on an external client, writing data to the system
- do something to the system that might cause DU (data unavailable,
  i.e. a write error)
- validate that the data written is correct

This script takes into account that data that has not been acknowledged
might be EITHER new or old data, therefore either is considered
valid.

Use Cntrl+C (SIGINT) to kill this program gracefully.

**returned error codes:**
- `0`: no errors
- `1`: write error, probably due to the device itself (DU)
- `2`: validation error, meaning corrupted data (DL)

# Usage
## Ultra Simple Usage
Simple usage would just be:
```
curl https://git.io/dataloss -L > dataloss && python dataloss /path/to/folder -a
```
This will download the script and call it. The script will
push data, waiting for a failure and constantly validating data

validate the data with:
```
python dataloss -v 
```

## Full usage (get through -h)
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
  -l LOG, --log LOG     log to write or validate from.
                        default=/tmp/dataloss.log
  -v, --validate        validate using logfile provided
  --bs BS               block size default=4096
  --blocks BLOCKS       num of blocks before wrapping. default=1000
  -a, --auto-validate   if set, data will be validated while writting takes
                        place
  --period PERIOD       period between writes. default=0
  --timeout TIMEOUT     time in seconds to write. default=inf
  --total-blocks TOTAL_BLOCKS
                        total number of blocks to write default=inf
```
