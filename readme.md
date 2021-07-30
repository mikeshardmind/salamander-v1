# Project Salamander

## What is this?

Project Salamander is a currently in development component
for a larger social presence moderation network.

It aims to be easy to use correctly, intuitive, and extensible.

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

## Goals

1. Provide the Discord Component for the moderation network.
2. Provide abstractions which are considered for performance, ease of use, and encouraging extensible code.
3. Be capable of being used with or without the larger network.

## Interaction with the larger network

Many portions of moderation end up being service specific.
Those that do, need either abstractions, or specific handling for just that particular service.

The network will have components which track various trends
and pass data about those trends between services to make better on the fly-decisions.

Project Salamander's role in this is as a moderation focused discord bot that
is designed to be hooked up to such a network. 

## You still have questions?

This is a relatively new project based on a mix of old ideas and newer motivations.

Development will happen based on discussions with invested parties. 

If you'd like to learn more, contact links will be added when we are ready to take questions and input from a wider audience. Stay tuned.


## Want to help?

If you'd like to join us in making spaces of the internet a bit easier to manage,
please discuss (open an issue or discuss in project spaces) prior to opening any pull request to coordinate.


## Current environemnt

python3.9 (cpython)
ubuntu server 20.04

This reflects the environment it will be tested on early in development, however
the final product should be deployable on any posix compatible OS,
including through docker, terraform, ansible and others.

## Installation

**The process of getting this up and running will be streamlined in the future.**

This section is not in a polished state as there is a lot left to streamline on this to make it more accessible.
For now, it serves as a very minimal documentation of what's needed to get this up, running and tested on ubuntu 20.04

Currently, this requires [hydra](https://github.com/unified-moderation-network/hydra) to be running.

The filter is designed as an external service (see [basilisk](https://github.com/unified-moderation-network/basilisk))
though there may be an option to enable a local filter in the future.


1. Install dependencies 

These are the specific packages required to build *everything* associated with the network
on Ubuntu 20.04 (to be streamlined in the future)

Many of these are build-time but not run-time dependencies, and if you intend to create a container, should not end up in the resulting image.

```
make build-essential libssl-dev zlib1g-dev libbz2-dev \
libreadline-dev libsqlite3-dev wget curl llvm libncurses5-dev \
xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev \
libgdbm-dev uuid-dev python3-openssl git libhyperscan5 libhyperscan-dev sqlite3
```

2. Install (or preferably, build with optimizations enabled) python3.9

3. run `setup.sh` from the direcotry which you want to run the bot (currently, you should only run one instance, this will be rectified in the near future)

  NB. This creates a binary wheel built against the sqlite3 amalgamation at a specific version, targeting the current architecture,
  and installs into the current `python3.9`.
  These steps do not need to be done together, and the wheel step specifically may be slow, while creating a resource which can be reused.
  This also needs improvement, but if run in the same directory, (or if the wheel is copied to an appropriate location before running again)
  this won't be regenerated.
  
  There's a lot to improve here.

4. copy default_config.toml -> config.toml and edit as appropriate

5. run the bot with SALAMANDER_TOKEN=XXX python3.9 runner.py

For examples of setting this up as a set of systemd services, see systemd.md
