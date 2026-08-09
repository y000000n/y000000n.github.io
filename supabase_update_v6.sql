-- 섀도잉을 방향 없는 활동으로 저장하기 위한 1회성 업데이트
alter table public.practices drop constraint if exists practices_direction_check;
update public.practices set direction = '없음' where activity_type = 'shadowing';
alter table public.practices
  add constraint practices_direction_check
  check (direction in ('KO→JA', 'JA→KO', '없음'));
