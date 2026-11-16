# Product brief: IPO Tracker

## Problem

Indian IPO coverage is built around the day an IPO opens: grey-market premiums, subscription numbers and listing-day pops. After listing, it's hard to answer the question an applicant actually has: *if I had been allotted, what would my application be worth now, and was it worth the money I had to block?* The answer depends on which category you applied in (retail, small HNI, big HNI, employee, shareholder), because each has a different minimum application, and on events like splits and bonuses that make raw prices misleading.

## Who it's for

- **Retail applicants** deciding whether IPOs in general, or a sector, have rewarded applying and holding.
- **HNI applicants** blocking ₹2–10 lakh or more per application, who need to see returns in rupees, not just percentages.
- **Employees and shareholders** eligible for reserved quotas, often at a discount.

## What success looks like

| Goal | Measure |
|---|---|
| People find an IPO and get an answer fast | Time from landing to viewing an IPO's category table; share of visits that reach an IPO page |
| The numbers are trusted | Zero validation errors on published data; listing-day prices match exchange figures |
| The date picker is useful | Share of IPO-page visits that change the date |
| The AI page answers well | Share of questions answered without a tool error; thumbs-up rate (future) |
| Data stays fresh | Days since the last successful price load (shown on the site); failed days in the last 30 |

## Scope of version one

In: 2026 mainboard, NSE Emerge and BSE SME IPOs (298 so far), all five categories, listing-day / today / any-date P&L, split and bonus adjustment, AI questions with a usage limit.

Out (for now): dividends and tax, live intraday prices, user accounts and saved portfolios, alerts.

## Key decisions and trade-offs

- **Show the minimum application per category**, because oversubscribed categories allot exactly that by lottery. Showing the maximum would overstate what a typical successful applicant got.
- **Official exchange data first**, Yahoo only to fill gaps; broker APIs left out (cost, daily token renewal, and licence limits on public display).
- **AI answers only from tool calls**, with the calls shown, so users can see where each number came from.

## Next

1. "Compare categories" view: return on money blocked, adjusted for allotment odds using subscription figures.
2. Saved watchlist and an email when a tracked IPO crosses a threshold.
3. Subscription figures for BSE SME IPOs (BSE publishes them per issue; not collected yet).

## Shipped since version one

- BSE SME platform IPOs (128 in 2026), which was the largest coverage gap: SME coverage went from 63 to 191 IPOs.
