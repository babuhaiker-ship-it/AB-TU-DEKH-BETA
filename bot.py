# Daily Free Scroll Feature Implementation

def daily_free_scroll(config):
    free_scroll_limit = config.get('daily_free_scroll_limit', 5)
    reset_time = config.get('daily_free_scroll_reset_time', 3600)  # in seconds
    return free_scroll_limit, reset_time


class FreeScroll:
    def __init__(self):
        self.usage = 0  # Tracks current free scroll usages
        self.last_reset = datetime.utcnow()

    def use_scroll(self):
        if self.usage < daily_free_scroll_limit:
            self.usage += 1
            return True  # Scroll was successfully used
        else:
            return False  # Scroll limit reached

    def reset_scrolls(self):
        if (datetime.utcnow() - self.last_reset).total_seconds() > reset_time:
            self.usage = 0
            self.last_reset = datetime.utcnow()

# Assuming 'user' is the current user object
free_scroll = FreeScroll()
config = {'daily_free_scroll_limit': 5, 'daily_free_scroll_reset_time': 3600}

# When a user tries to navigate
free_scroll.reset_scrolls()
if not free_scroll.use_scroll():
    alert_user('You have reached your daily free scroll limit. Please wait until reset.')</code>