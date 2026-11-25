"""Visit each visible mall red marker at most once per viewport and task."""
from maa.custom_recognition import CustomRecognition


class MallRedOnce(CustomRecognition):
    def __init__(self):
        super().__init__()
        self.visited = {}

    def analyze(self, context, argv):
        key = (argv.task_detail.task_id, argv.node_name)
        if len(self.visited) > 200:
            self.visited.clear()
        visited = self.visited.setdefault(key, [])
        detail = context.run_recognition('ShoppingMallRedMarkerRaw', argv.image)
        if not detail or not detail.hit:
            return None
        for result in detail.filtered_results:
            box = result.box
            if isinstance(box, (list, tuple)):
                if len(box) != 4:
                    continue
                x, y, w, h = box
            else:
                x, y, w, h = box.x, box.y, box.w, box.h
            center = (x + w // 2, y + h // 2)
            if any(abs(center[0] - old[0]) < 30 and abs(center[1] - old[1]) < 45 for old in visited):
                continue
            visited.append(center)
            return (x, y, w, h)
        return None
