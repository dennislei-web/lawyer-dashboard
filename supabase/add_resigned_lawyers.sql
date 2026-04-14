-- Step 1: Add is_active column
ALTER TABLE public.lawyers ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;

-- Step 2: Mark 黃惠群 as inactive (already in table)
UPDATE public.lawyers SET is_active = false WHERE name = '黃惠群';

-- Step 3: Insert resigned lawyers
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('丁巧欣', 'resigned_丁巧欣@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('劉羽芯', 'resigned_劉羽芯@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('吳書晴', 'resigned_吳書晴@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('唐于淇', 'resigned_唐于淇@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('張佳榕', 'resigned_張佳榕@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('張紹成', 'resigned_張紹成@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('徐佳緯', 'resigned_徐佳緯@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('方浚煜', 'resigned_方浚煜@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('李仁傑', 'resigned_李仁傑@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('李家徹', 'resigned_李家徹@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('李音忻', 'resigned_李音忻@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('杜柏賢', 'resigned_杜柏賢@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('林俐妤', 'resigned_林俐妤@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('林貝珍', 'resigned_林貝珍@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('林雨辰', 'resigned_林雨辰@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('楊于瑾', 'resigned_楊于瑾@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('楊喬伊', 'resigned_楊喬伊@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('楊筑鈞', 'resigned_楊筑鈞@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('游政恩', 'resigned_游政恩@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('紀宜君', 'resigned_紀宜君@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('紀淑卿', 'resigned_紀淑卿@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('莊清翊', 'resigned_莊清翊@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('蔡宛陵', 'resigned_蔡宛陵@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('蔡愷凌', 'resigned_蔡愷凌@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('蕭予馨', 'resigned_蕭予馨@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('郭玟樺', 'resigned_郭玟樺@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('陳宛婷', 'resigned_陳宛婷@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('陳沛羲', 'resigned_陳沛羲@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('黃裕恆', 'resigned_黃裕恆@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
INSERT INTO public.lawyers (name, email, role, office, is_active) VALUES ('黃鈺婷', 'resigned_黃鈺婷@placeholder.com', 'lawyer', '喆律法律事務所', false) ON CONFLICT DO NOTHING;
