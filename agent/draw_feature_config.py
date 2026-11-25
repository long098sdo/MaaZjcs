"""Validate explicit independent draw targets without spending resources."""


TREE = ('结缘',)
WISH = ('高阶祈愿', '常驻祈愿', '友情祈愿')
GACHA = ('国度蓝券', '国度紫券', '国度橙券', '国度金券',
         '元素风', '元素水', '元素火', '元素光', '元素暗')

WISH_NODES = dict(zip(WISH, ('WishTargetAdvanced', 'WishTargetRegular', 'WishTargetFriend')))
COUNTRY_NODES = dict(zip(GACHA[:4], ('GachaTargetBlue', 'GachaTargetPurple', 'GachaTargetOrange', 'GachaTargetGold')))


def read_node_targets(context, nodes):
    """Each setting has its own pipeline node, so MFA cannot replace sibling values."""
    values = {}
    for pool, name in nodes.items():
        node = context.get_node_data(name)
        try:
            param = node['action']['param']['custom_action_param']
            if isinstance(param, str):
                import json
                param = json.loads(param)
            values[pool] = param['value']
        except (KeyError, TypeError, ValueError):
            raise ValueError(f'{pool}设置缺失，停止执行')
    return validate_targets(values, tuple(nodes))


def validate_targets(values, pools):
    if not isinstance(values, dict) or set(values) != set(pools):
        raise ValueError('池子设置缺失或包含未验证的池子')
    values = {key: int(value) if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 5 else value for key, value in values.items()}
    if any(type(value) is not int or not 0 <= value <= 10000 for value in values.values()):
        raise ValueError('次数必须是0到10000的整数')
    return dict(values)
