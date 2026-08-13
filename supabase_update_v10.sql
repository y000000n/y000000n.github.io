-- 언어쌍 중요 표시(⭐) 기능을 위한 1회성 업데이트
-- 기존 언어쌍은 삭제되지 않으며 중요 표시가 해제된 상태(false)로 유지됩니다.

alter table public.language_pairs
  add column if not exists important boolean not null default false;

alter table public.language_pairs
  alter column pair_type set default 'other';
