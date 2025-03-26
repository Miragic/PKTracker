-- 任务表索引
CREATE INDEX IF NOT EXISTS idx_task_group ON t_task(group_id);
CREATE INDEX IF NOT EXISTS idx_task_name ON t_task(task_name);
CREATE INDEX IF NOT EXISTS idx_task_enable ON t_task(enable);

-- 打卡记录表索引
CREATE INDEX IF NOT EXISTS idx_checkin_task ON t_checkin_log(task_id);
CREATE INDEX IF NOT EXISTS idx_checkin_user ON t_checkin_log(user_id);
CREATE INDEX IF NOT EXISTS idx_checkin_time ON t_checkin_log(checkin_time);

-- 管理员表索引
CREATE INDEX IF NOT EXISTS idx_admin_group ON t_admin(group_id);
CREATE INDEX IF NOT EXISTS idx_admin_user ON t_admin(user_id);

-- 积分表索引
CREATE INDEX IF NOT EXISTS idx_bonus_task ON t_bonus(task_id);
CREATE INDEX IF NOT EXISTS idx_bonus_user ON t_bonus(user_id);
CREATE INDEX IF NOT EXISTS idx_bonus_date ON t_bonus(date_awarded);