# Packing categories — the sweep

Used by `/travel-packing:inventory` in category-sweep mode, when the packing has not happened
yet. Walk them in order and ask what is going in each. The order is deliberate: it front-loads
the categories that dominate the weight and ends with the ones people actually remember
unprompted.

Also the default cube grouping: one category per packing cube where the cube count allows.

1. **Footwear** — every pair, including the pair being worn. Heaviest category per item.
2. **Outerwear** — coats, jackets, rainwear. Ask which one is being worn; a worn coat is not
   weighed.
3. **Electronics and cables** — devices, chargers, adapters, power banks, headphones, and the
   pouch they live in. Ask about the accessories separately from the devices; they are
   routinely half the weight and always forgotten.
4. **Toiletries and medication** — full-size vs travel-size, and what is prescription. This is
   where the liquids constraint and the cabin-only constraint both bite.
5. **Clothing — tops** — by count, not by outfit. Counting outfits reliably overestimates.
6. **Clothing — bottoms**
7. **Clothing — underwear and socks** — count, and ask whether there is laundry at the
   destination. Laundry access is worth more weight than any packing technique.
8. **Sleepwear and swimwear**
9. **Documents** — passports, visas, insurance, tickets, prescriptions, vaccination records.
   No weight worth modelling; entirely trip-ending if missed. Always cabin.
10. **Work or purpose kit** — whatever the trip is actually for: instruments, samples, sports
    equipment, a gift, professional tools. Ask directly; it does not fit the other categories
    and it is often the single heaviest item.
11. **Gifts and things being delivered** — including anything being carried for someone else.
    Ask what is in it. This is the one category where the traveller may not know.
12. **Food and drink** — snacks, coffee, anything being brought because it is not available at
    the destination. Dense, and subject to import restrictions worth checking separately.
13. **Books and paper**
14. **Comfort and contingency** — travel pillow, eye mask, umbrella, spare bag, laundry bag.
    Ends the sweep because it is the category most safely cut.

## Two questions that change the whole inventory

Ask both before the sweep, not after:

- **Is there laundry at the destination?** If yes, clothing counts drop by roughly half on any
  trip longer than a week, and that is a larger saving than every packing optimisation
  combined.
- **What is genuinely unavailable where you are going?** The honest answer is usually "very
  little", and it converts a lot of `tier: essential` into `replaceable_at_destination`.
