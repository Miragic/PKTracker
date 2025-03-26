import requests

from common.log import logger
from config import conf


class UserManager:
    def __init__(self, client, app_id):
        self.client = client
        self.app_id = app_id

    def _get_user_id_by_nickname(self, nickname):
        """根据昵称或备注名获取用户 ID"""
        try:
            # 获取所有联系人列表
            contacts_response = self.client.fetch_contacts_list(self.app_id)
            print(f"[PKTracker] fetch_contacts_list 返回数据: {contacts_response}")  # 打印返回数据
            if contacts_response.get('ret') == 200:
                # 提取好友的 wxid 列表
                wxids = contacts_response.get('data', {}).get('friends', [])
                print(f"[PKTracker] 提取的 wxids: {wxids}")  # 打印提取的 wxids

                # 如果 wxids 为空，直接返回 None
                if not wxids:
                    logger.error("[PKTracker] 未找到有效的 wxid")
                    return None

                # 分批获取详细信息（每次最多 20 个 wxid）
                for i in range(0, len(wxids), 20):
                    batch_wxids = wxids[i:i + 20]  # 每次最多 20 个 wxid
                    # 获取当前批次的详细信息
                    detail_response = self.client.get_detail_info(self.app_id, batch_wxids)
                    print(f"[PKTracker] get_detail_info 返回数据: {detail_response}")  # 打印详细信息
                    if detail_response.get('ret') == 200:
                        details = detail_response.get('data', [])
                        # 遍历详细信息，查找匹配的昵称或备注名
                        for detail in details:
                            # 检查昵称或备注名是否匹配
                            if detail.get('nickName') == nickname or detail.get('remark') == nickname:
                                return detail.get('userName')  # 返回 wxid
        except Exception as e:
            logger.error(f"[PKTracker] 获取用户信息失败: {e}")
            return None

    def _get_user_nickname(self, user_id):
        """获取用户昵称"""
        try:
            response = requests.post(
                f"{conf().get('gewechat_base_url')}/contacts/getBriefInfo",
                json={
                    "appId": conf().get('gewechat_app_id'),
                    "wxids": [user_id]
                },
                headers={
                    "X-GEWE-TOKEN": conf().get('gewechat_token')
                }
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('ret') == 200 and data.get('data'):
                    return data['data'][0].get('nickName', user_id)
            return user_id
        except Exception as e:
            logger.error(f"[PKTracker] 获取用户昵称失败: {e}")
            return user_id

    def _get_nickname_by_user_ids(self, user_ids):
        """批量获取用户昵称"""
        if not user_ids:
            return {}

        try:
            response = requests.post(
                f"{conf().get('gewechat_base_url')}/contacts/getBriefInfo",
                json={
                    "appId": conf().get('gewechat_app_id'),
                    "wxids": user_ids
                },
                headers={
                    "X-GEWE-TOKEN": conf().get('gewechat_token')
                }
            )

            if response.status_code == 200:
                data = response.json()
                if data.get('ret') == 200 and data.get('data'):
                    # 构造 user_id -> nickName 映射
                    user_map = {item.get("userName", uid): item.get("nickName", uid) for item, uid in
                                zip(data['data'], user_ids)}
                    return user_map

            # 如果请求失败或数据不完整，返回默认映射
            return {uid: uid for uid in user_ids}

        except Exception as e:
            logger.error(f"[PKTracker] 批量获取用户昵称失败: {e}")
            return {uid: uid for uid in user_ids}
