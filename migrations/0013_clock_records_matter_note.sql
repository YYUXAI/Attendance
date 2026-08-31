ALTER TABLE public.clock_records
  ADD COLUMN IF NOT EXISTS matter_note TEXT;
