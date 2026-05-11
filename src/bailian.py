"""
百炼英雄小程序游戏辅助脚本
"""
from math import sqrt

import pyautogui
import time
import random
import threading
from datetime import datetime

from src.conf import *
from src.card_conf import *
from src.router import RouterA
from src.enums import CardMap


class Base:

    def __init__(self, stop_event=None):
        self.duration = 0.5  # 鼠标移动间隙速度
        self._stop_event = stop_event or threading.Event()

    def _stop_check(self):
        """检查是否需要停止任务"""
        return self._stop_event.is_set()

    def timeout(self, sec):
        """等待指定秒数，stop_event 被设置时提前返回"""
        self._stop_event.wait(timeout=sec)

    def move_mouse(self, x, y, click=False, click_count=1, sec=0):
        # 移动鼠标到指定坐标 (1000, 410)
        pyautogui.moveTo(x, y, duration=self.duration)  # 用0.5秒时间移动鼠标到目标位置
        # 点击鼠标左键
        if click:
            # print(f'点击了按钮', x, y)
            for i in range(click_count):
                pyautogui.click()
                self.timeout(1.2)
        self.timeout(sec)

    def click(self, button_name, sec=0, if_click=True, click_count=1):
        self.move_mouse(*BUTTONS[button_name], click=if_click, click_count=click_count)
        self.timeout(sec)

    def click_back_home(self, sec=8):
        # 每个地图回城的时间不同，王座大厅图回城需要8s， 黑市堡垒需要10s
        self.click(BT_HOME)
        self.click(BT_OK, sec=sec)

    def click_level(self, level, raw="A", sec=10, if_click=True):
        area = MAP_LEVEL_A_BUTTON[f'LEVEL_{level[:1]}']
        if raw == "A":
            self.move_mouse(*area, click=if_click)
            self.move_mouse(*MAP_LEVEL_A_SUB_BUTTON[level], click=if_click)
        if raw == "B":
            self.move_mouse(*MAP_LEVEL_B_SUB_BUTTON[level], click=if_click)
        self.timeout(sec)

    def move(self, direction, cons_sec, sec=2):
        pyautogui.moveTo(*BUTTONS[CENTER])
        pyautogui.mouseDown()
        pyautogui.moveTo(*FORWARD_POINT[direction], duration=cons_sec)
        pyautogui.mouseUp()

        print(f'往{direction}行动了')
        self.timeout(sec)

    def check_city_load_complete(self, limit=12):
        # 因为各个地图的回城的加载时间不一致，所以这里稍微多等待几秒,最多等待12s则报错
        count = 0
        status = False
        while not self._stop_check():
            count += 1
            if pyautogui.pixel(*BUTTONS[BT_TRAN]) == BUTTONS_COLORS[BT_TRAN]:
                self.click(BT_TRAN)
                status = True
            if pyautogui.pixel(*BUTTONS[BT_TRAN_BACK]) == BUTTONS_COLORS[BT_TRAN]:
                self.click(BT_TRAN_BACK)
                status = True
            if status:
                print(f'该地图加载时间为{count}s')
                return
            self.timeout(1)
            if count >= limit:
                raise TimeoutError('加载主地图失败，请保证主窗口为初始位置')


class DrawCard(Base):
    """
    抽卡脚本v1.0
        1、通过特定坐标颜色RGB值，判定是否为白卡，蓝卡，紫卡，金卡，红卡，灰色
            如果存在金卡，或者红卡，则自动调整金币300进行抽卡
    """

    def __init__(self, stop_event=None):
        super().__init__(stop_event)
        # 初始化抽卡状态存储
        self.card_pos_color = {"A": "", "B": "", "C": ""}
        self.card_role = {"A": "", "B": "", "C": ""}
        self.card_role_rev = {}
        self.card_total_count = 3
        self.card_color = list()
        self.card_status = {"A": False, "B": False, "C": False}
        self.card_draw_times = {"A": 0, "B": 0, "C": 0}


        # 统计
        self.count = 0
        self.red_count = 0
        self.gold_count = 0

    def check_card_color(self):
        for card, pos in CARD_SHOW_POS.items():
            self.card_pos_color[card] = COLOR_POINT.get(pyautogui.pixel(*pos), "white")
        self.card_color = list(self.card_pos_color.values())
        print(f'本次三张卡颜色分别为: {self.card_color}')

    def refresh_card_status(self):
        for card, pos in CARD_SHOW_STATUS.items():
            self.card_status[card] = True if pyautogui.pixel(*pos) == BUTTONS_COLORS[BT_OK] else False
        print(f'本次三张卡抽取状态分别为: {list(self.card_status.values())}')

    def check_card_status(self):
        """
        todo 目前仅支持抽取一次
        return 0 表示不抽取，1表示可抽取"""
        if any(list(self.card_status.values())):
            return 0
        return 1

    @staticmethod
    def rgb_similarity(rgb1, rgb2, threshold=0.97):
        """
        计算两个RGB颜色的相似度，并与阈值比较

        参数:
        rgb1 -- 第一个RGB颜色，格式为元组 (R, G, B)
        rgb2 -- 第二个RGB颜色，格式为元组 (R, G, B)
        threshold -- 相似度阈值(0-1)，低于此值返回False

        返回:
        bool -- 如果相似度 >= 阈值返回True，否则返回False
        """
        # 计算欧几里得距离
        distance = sqrt(sum((c1 - c2) ** 2 for c1, c2 in zip(rgb1, rgb2)))

        # 最大可能的RGB距离(黑色到白色)
        max_distance = sqrt(3 * (255 ** 2))

        # 将距离转换为相似度(0-1)
        similarity = 1 - (distance / max_distance)

        return similarity > threshold

    def check_card_role(self):
        """根据阈值范围模糊判定角色为哪个卡
        优点：准确
        缺点：性能差, 可能识别错"""
        self.card_role = {"A": "", "B": "", "C": ""}
        for i in range(self.card_total_count):
            color = self.card_color[i]
            for role, points in eval(f'CARD_KEY_POINT_{color.upper()}').items():
                if points[i]:
                    role_rgb = eval(f'ROLE_KEY_RGB_{color.upper()}')
                    for rgb in list(role_rgb.keys()):
                        if self.rgb_similarity(pyautogui.pixel(*points[i]), rgb):
                            print(i, role_rgb[rgb], pyautogui.pixel(*points[i]), rgb)
                            print(points[i], role_rgb[rgb])
                            self.card_role[CARD_LIST[i]] = role_rgb[rgb]
                            break
                    if self.card_role[CARD_LIST[i]]:
                        break
        self.card_role_rev = {v: k for k, v in self.card_role.items()}
        print(f'本次三张卡角色分别为: {self.card_role}')

    def click_drop(self, sec=4):
        self.move_mouse(*BUTTONS['drop'], click=True)
        # 统计抽到的卡数
        for card, status in list(zip(self.card_color, list(self.card_status.values()))):
            if card == 'red' and status:
                self.red_count += 1
            if card == 'gold' and status:
                self.gold_count += 1
        self.timeout(sec + random.randint(2, 4))

    def check_new_page(self):
        if not any(list(self.card_status.values())):
            print(f'目前是新的一页抽卡')
        else:
            print(f'目前是旧的一页待第二次抽卡')

    def load_diamond_set(self):
        for role in list(self.card_role.values()):
            if role in ALLOW_ALLIN_ROLE:
                self.card_draw_times[self.card_role_rev[role]] = ALLOW_ALLIN_ROLE[role]

    def if_continue_draw(self):
        # todo 需要测试
        self.refresh_card_status()
        for card, times in self.card_draw_times.items():
            if not self.card_status[card]:
                #  仅当状态为False(说明卡未被抽)且当抽取次数>0的时候需要继续用钻石抽取
                if times > 0:
                    self.click(BT_DRAW, sec=4)
                    # 检测是否钻石不足, 不足直接退出
                    if pyautogui.pixel(*BUTTONS[FLOOR1]) == BUTTONS_COLORS[FLOOR1]:
                        self.click(BACK_HOME, sec=2)
                        return True
                    self.refresh_card_status()
                    if not self.card_status[card]:
                        self.click(BT_DRAW, sec=4)
                    else:
                        continue
                else:
                    continue

    def run(self):
        """主逻辑执行"""
        while not self._stop_check():
            print('')
            # 判断ABC三张卡颜色
            self.check_card_color()
            # 判断三张卡角色
            # self.check_card_role()
            # 整理钻石设定
            self.load_diamond_set()
            # 刷新卡状态
            self.refresh_card_status()
            self.check_new_page()

            # 如果金卡或红卡状态未抽取就进行抽取, 若已经抽取完了某个，就点放弃，直接进入下一轮
            if self.check_card_status():
                # 如果有金卡或红卡，则调整倍数为最大
                if "gold" in self.card_color or "red" in self.card_color:
                    self.click(BT_RATE)
                self.click(BT_DRAW, sec=3)
                self.count += 1
                # 判定是否存在高倍钻石抽取设定，若指定金红卡被抽取，则继续，若未抽取，则继续用钻石抽取
                # if self.if_continue_draw():
                self.click_drop()
            else:
                self.click_drop()
                print(
                    f'目前抽取结果汇总=======>> 抽取次数：{self.count}, 红卡次数：{self.red_count}, 金卡次数：{self.gold_count}')
            # self.check_card_role()
            print('开启循环下一次')


class AutoFight(Base, RouterA):
    """指定特定关卡进行自动路线清本"""

    def __init__(self, stop_event=None):
        super().__init__(stop_event)
        # 首先确保自己自己在主城
        self.click_back_home()

    def rush_all(self):

        # todo on develop 遍历地图序号，开始刷图，
        for level in list(MAP_LEVEL_A_SUB_BUTTON.keys())[:1]:
            # 若不是1-1关，则打开传送阵，点击传送到对应关卡位置
            if level != "1-1":
                self.click(BT_TRAN)
                self.click_level(MAP_LEVEL_A_SUB_BUTTON)
            self.rush_map(level)

    def rush_wood(self):
        # 进入战斗
        while not self._stop_check():
            self.check_city_load_complete()
            self.click_level(WOOD_LEVEL)
            for direction, sec in WOOD_ROUTER:
                if self._stop_check():
                    return
                self.move(direction, sec)
            self.click_back_home()


class DailyTask(Base):
    """日常"""

    def __init__(self, stop_event=None):
        super().__init__(stop_event)
        self.duration = 0.2  # 鼠标移动间隙速度
        self.box_limit = 30  # 每日箱子最大领取次数
        self.pk_limit = 4  # 每日免费战斗次数
        # 首先确保自己自己在主城
        self.click_back_home()

    def rush_all(self):
        # 点掉初始的各种活动弹窗, 点个什么五六次
        self.click(FLOOR, click_count=5)
        # 点商城,其中每周礼包只有周一才能点
        self.click_shop()
        # 每日签到
        self.click_sign()
        # 每日挑战
        self.click_battle()
        # 英雄馈赠
        self.click_hero_card()
        # 刷箱子
        self.rush_quick()

    def click_battle(self):
        # PK竞技场 每日4次

        self.click(PK, sec=5)  # 第一次加载比较慢
        self.click(BT_FIELD)

        while self.pk_limit:
            self.click(VS, sec=12)
            self.click(FLOOR, sec=3)
            self.pk_limit -= 1
        self.click(BACK_HOME, sec=2)

    def rush_quick(self):
        # 快速拿箱子，刷8-2 F4
        # 进入战斗
        while self.box_limit and not self._stop_check():
            self.check_city_load_complete()
            self.click_level(DAILY_LEVEL)
            for num, router in enumerate(F4_ROUTER, start=1):
                # todo 需要解决1、中断后需检测还可以看几次广告，2、解决报错问题，若报错需要重来
                self.move(router[0], router[1], sec=1)
                if self._stop_check():
                    return
                if num % 2 == 0:
                    self.timeout(4)
                    self.pick_box(num // 2)
                    self.click_back_home()

    def pick_box(self, num):
        # todo 箱子刷新的位置有时候会有变动,需增加一个适配坐标
        self.move_mouse(*BOX_BUTTON[num - 1], click=True, sec=1)
        # 如果可以看视频双倍，则点击,看广告30s
        if pyautogui.pixel(*BUTTONS[REWARD]) == BUTTONS_COLORS[REWARD]:
            self.click(REWARD, sec=35)
            self.click(CANCEL_AD, click_count=3)
        else:
            self.click(RECEIVE, sec=2)
            self.click(FLOOR)
        self.box_limit -= 1

    def click_shop(self):

        self.click(SHOP)  # 点击商店
        self.click(TH_GIFT)  # 点击特惠礼包
        self.click(DAY_BAO)  # 点击每日礼包
        self.click(DAY_GIFT)  # 点击免费领取
        if not self.check_monday():  # 周一执行
            self.click(WEEK_BAO)  # 点击每周礼包
            # self.click(WEEK_GIFT)  # 点击免费领取
        self.click(BACK_HOME, sec=2)  # 点击退出

    def click_sign(self):
        self.click(FULI)  # 点击福利
        self.click(DAILY_SIGN)  # 点击福利
        self.click(GET_SIGN)  # 点击福利
        self.click(BACK_HOME, sec=2)  # 点击福利

    def click_hero_card(self):
        self.click(ACT)  # 点击福利
        self.click(ACT_HERO)  # 点击福利
        self.click(GET_HERO)  # 点击福利
        self.click(BACK_HOME, sec=2)  # 点击福利

    @staticmethod
    def check_monday():
        return datetime.now().weekday()


if __name__ == '__main__':
    # 抽卡
    # dc = DrawCard()
    # dc.run()

    # dc.check_card_color()
    # dc.check_card_role()

    # 刷木头
    AutoFight().rush_wood()

    # 刷日常
    # DailyTask().rush_all()
    # DailyTask().rush_quick()
    # DailyTask().click_battle()
    # DailyTask().click_hero_card()
