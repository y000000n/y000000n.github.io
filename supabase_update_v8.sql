-- 공부 자료 게시글 분류 추가: 기존 Supabase 프로젝트에서 한 번 실행하세요.
alter table public.study_materials
  add column if not exists language_direction text not null default '한일';

alter table public.study_materials
  add column if not exists interpretation_mode text not null default '동시';
