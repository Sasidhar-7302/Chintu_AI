---
name: price compare
description: Compares prices for any product across major retailers and optionally broader trusted websites, then saves a markdown table. Use for product price comparisons, deal checks, and "save comparison table" style requests.
triggers:
  - price compare
  - compare prices
  - best price for
  - find the best price for
  - find best price for
  - price comparison table
  - save comparison table
  - compare products
  - compare prices across websites
command: python {SKILL_DIR}/compare_prices.py "{request}"
args:
  - request
type: shell
requires-bin:
  - python
metadata:
  policy:
    risk: low
    requires_confirmation: false
    requires_internet: true
---
