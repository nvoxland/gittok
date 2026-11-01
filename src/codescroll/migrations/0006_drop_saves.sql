-- The Save feature is gone (Like is the only reaction): delete its stored events.
DELETE FROM events WHERE type = 'save';
