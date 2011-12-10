# README
x6500-miner is a set of code designed for working with the X6500 FPGA Miner boards, which are used for bitcoin mining.

## Dependencies
The main dependencies are python 2.7 and the PyUSB module created by Pablo Bleyer. PyUSB is available as source or an installer for Windows from: http://bleyer.org/pyusb.

For Linux, you will need to build and install my modified version of the PyUSB module. This is available from http://fpgamining.com/software.

## Usage
There are two python scripts that you will need to use to mine with an X6500. The first is _program.py_, which will program the FPGA and prepare it for bitcoin mining. This needs to be run every time power is removed from the board or if you want to load a different bitstream. The second script is _mine.py_, which handles the communication between the pool and the X6500.

### program.py
```
Usage: program.py [-d <devicenum>] [-c <chain>] <path-to-bitstream-file>

Options:
  -h, --help            show this help message and exit
  -d DEVICENUM, --devicenum=DEVICENUM
                        Device number, default 0 (only needed if you have more
                        than one board)
  -c CHAIN, --chain=CHAIN
                        JTAG chain number, can be 0, 1, or 2 for both FPGAs on
                        the board (default 2)
  -v, --verbose         Verbose logging
```

### mine.py
```
Usage: mine.py [-d <devicenum>] [-c <chain>] -u <pool-url> -w <user:pass>

Options:
  -h, --help            show this help message and exit
  -d DEVICENUM, --devicenum=DEVICENUM
                        Device number, default 0 (only needed if you have more
                        than one board)
  -c CHAIN, --chain=CHAIN
                        JTAG chain number, can be 0, 1, or 2 for both FPGAs on
                        the board (default 2)
  -i GETWORK_INTERVAL, --interval=GETWORK_INTERVAL
                        Getwork interval in seconds (default 30)
  -v, --verbose         Verbose logging
  -u URL, --url=URL     URL for the pool or bitcoind server, e.g. pool.com:8337
  -w WORKER, --worker=WORKER
                        Worker username and password for the pool, e.g. user:pass
```

