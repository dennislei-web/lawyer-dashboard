SELECT column_name, is_nullable, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'lawyers' AND table_schema = 'public'
ORDER BY ordinal_position;
