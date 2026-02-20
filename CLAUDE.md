# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository implements **EX4: Asynchronous MPC for omission failures** from the RDS 2026 course. The exercise has three options (at least one required):

1. **Theory component** (questions 1.1-1.7): Designing protocols for asynchronous MPC
2. **System Project 1**: Implementing a second-price auction with n=4, f=1
3. **System Project 2**: Adding unlinkable payments to EX3 with n=5, f=2

## System Model

**Core assumptions across all options:**
- **n = 3f+1 parties** (or 2f+1 for System Project 2) in asynchronous network
- Adversary: adaptive, computationally unbounded, corrupts up to f parties
- **Omission failures only**: corrupt parties may omit messages but never send incorrect ones
- Computation over large finite field F
- **Randomness beacon**: provides ρi ∈ F when f+1 parties request the ith value

## Key Protocols and Primitives

### Complete Secret Sharing (CSS)
Strengthened VSS with properties: Termination, Hiding, Binding, Completeness, Validity
- `share()` and `recover()` operations
- Degree f polynomials over F

### Agreement on Common Set (ACS)
Randomized agreement primitive for asynchronous setting:
- Each party proposes vi
- Output: set V with n-f proposals, containing ≥n-2f honest inputs
- Enables coordination despite omissions

### Secret Sharing Operations
- **Addition**: local operation on shares
- **Multiplication**: BGW approach with degree reduction
  - Local multiplication produces degree 2f sharing
  - Use ACS to agree on interpolation set T
  - Degree reduction back to f using Lagrange coefficients

### Second-Price Auction Function
- Input: bids xi ∈ [0, 2^k) from parties in set I, |I| = n-f
- Output: winner gets second-highest bid value, others get 0
- Requires bit decomposition for arithmetic circuit implementation

## Development Guidelines

### For System Projects

**Event-driven architecture required:**
- No synchronous rounds or blocking waits
- Handle messages asynchronously as they arrive
- Parties must handle omissions and arbitrary delays

**Testing requirements:**
- Honest execution scenarios
- Single omitting party scenarios
- Random message delays
- Unlinkability tests (System Project 2)

**Metrics to track:**
- Total messages sent
- Beacon invocations
- Time to completion

### Beaver Multiplication Triplets (Bonus)

Offline preprocessing of (a,b,c) where c=ab:
- Generate during preprocessing phase using beacon + CSS
- Online phase: constant-round multiplication
- Benchmark and compare with/without triplets

## System Project Specifics

### Project 1: Auction Implementation
- n=4 parties, f=1, bids in [0, 32) (5-bit integers)
- Unique bids assumption
- Comparison via bit decomposition + arithmetic circuits
- Output masking: only winner learns their output

### Project 2: Unlinkable Payments
- n=5 servers, f=2, 5 clients
- Pre-existing threshold signing key (assume DKG completed)
- Fixed denomination: value 1
- Operations: Mint (consume balance), Pay (transfer token)
- **Unlinkability**: observer cannot link Pay to originating Mint
- No multi-input payments, no change tokens

## Important Constraints

- **Asynchronous model**: cannot rely on synchrony or global rounds
- **Omission-only**: parties never send malformed messages
- **Termination**: randomized (probability 1) via beacon, not deterministic
- **Field arithmetic**: all operations over F, use bit decomposition for comparisons
