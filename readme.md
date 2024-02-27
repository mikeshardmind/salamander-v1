# Project Salamander (discontinued)

## Discontinuation

Below is retained for any inhteresting historical context. Use of this is not supported.

### Easy to use correctly, intutive

Commands which face users should be intuitive with safe default behavior.

Interfaces which are exposed to developers should be clear in purpose.
These interfaces should provide good behavior with performance
taken into consideration by default. Interfaces will be limited to
providing what is needed, using clear limitations on the scope of an interface
to ensure that no interface is a performance risk.

Underlying mechanisms which are built by maintainers should not take on
complexity without consideration and benefit to other goals.

### Extensible

Extensibility will be limited to providing a means of adding plugins,
no user facing mechanism will be provided to install additional plugins,
this is only a feature intended to be exposed to developers.

## Dev pace

This is a project based on a mix of old ideas and newer motivations. When there's a moment to work on improving it, I do here and there.

## Current environemnt

python3.10 (cpython)
ubuntu server 20.04

This reflects the environment I have the time to personally confirm it works on. This could be expanded in the future.

## Installation

This section is not in a polished state as there is a lot left to streamline on this to make it more accessible.
For now, it serves as a very minimal documentation of what's needed to get this up, running and tested on ubuntu 20.04

While this does not require hydra.py to be running, some features will not work without it.

The filter is designed as an external service basilisk.py
though there may be an option to enable a local filter in the future.


1. Install (or preferably, build with optimizations enabled) python3.10

2. Install dependencies (python3.10 -m pip install -U -r requirements-lax.txt --upgrade-strategy eager)

3. copy default_config.toml -> config.toml and edit as appropriate

4. run the bot with SALAMANDER_TOKEN=XXX python3.10 runner.py

For examples of setting this up as a set of systemd services, see systemd.md
