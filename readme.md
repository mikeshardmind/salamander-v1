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

Development will happen sporadically based on discussions with invested parties. 

If you'd like to learn more, contact links will be added when we are ready to take questions and input from a wider audience. Stay tuned.


## Want to help?

If you'd like to join us in making spaces of the internet a bit easier to manage,
please discuss (open an issue or discuss in project spaces) prior to opening any pull request to coordinate.


## Current environemnt

python3.8 (cpython)
ubuntu server 20.04

This reflects the environment it will be tested on early in development, however
the final product should be deployable on any posix compatible OS,
including through docker, terraform, ansible and others.