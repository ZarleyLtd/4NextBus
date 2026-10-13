# Extend 4NextBus to LUAS, Dart, and local train

Noted 11 October 2026, from the 4NextTram recognition work.

4NextBus stays the skill people open. LUAS, Dart, and local train are extra phrases inside it. Alexa already resolves "ask four next bus" on this account and does not reliably resolve "ask four next tram".

## Why

History shows "ask four next tram" heard as "ask for next tram". Alexa then answers "I don't know that location yet" and never calls the tram skill. "Open four next tram" does open it. "Ask for next bus" opens 4NextBus. Words after a recognized invocation are handled inside the skill. "Alexa, ask four next bus from stop 184" already works that way.

## Phrases to add, in one certification

Use "or LUAS", not "or tram". "Tram" and "train" are too easy to mix up. "LUAS" is not.

- "Alexa, ask four next bus or LUAS"
- "Alexa, ask four next bus or LUAS from Dundrum southbound"
- "Alexa, ask four next bus to set my favourite LUAS stop to Dundrum southbound"
- The same shape for Dart and local train.

Give the LUAS slot the likely mishearings: Lewis, Louis, Lucas, loos. Keep the bus favourite as a stop number. Store a separate favourite for each other mode, including direction where the mode needs it. A station on more than one mode, such as Connolly, must follow the mode word.

## Certification

New intents and slot types are a full recertification of the development version. Live 4NextBus keeps serving until that version is published. Point the development version at a test Lambda so the live bus function is unchanged. Include only modes that already return a real timetable. Test the full sentences on a device first. History must show 4NextBus, and the reply must be the right service.

## After it works

Remove 4NextTram, 4NextDart, and 4NextLocalTrain. Until then, "open four next tram" is the only tram phrase that already works, and retiring that skill deletes it. The spoken form remains "four next bus", because a published invocation cannot be renamed.
