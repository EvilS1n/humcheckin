import asyncio
import requests
from playwright.async_api import async_playwright
from typing import Dict

# Константы селекторов
CONNECT_WALLET_XPATH = "/html/body/div[4]/div/div/div/div[1]/div/div/button"
SKIP_BUTTON_XPATH = "//*[@id='app']/div/div[2]/div/div[6]/div/div[1]"
REWARD_XPATH = "//*[@id='app']/div/div[2]/div/div[3]/div[1]/div[2]/div[4]"
METAMASK_BUTTON_XPATH = "/html/body/div[6]/div/div/div[2]/div/div/div/div/div/div[2]/div[2]/div[1]/button"
SIGN_MESSAGE_BUTTON_XPATH = "/html/body/div[6]/div/div/div[2]/div/div/div/div/div[2]/div[2]/button[1]/div"
CONFIRM_CLAIM_XPATH = "//*[@id='app-content']/div/div/div/div/div[3]/button[2]"

# Настройки профилей
PROFILES = [

    {
        "profile_id": "",
        "metamask_password": "",
    },

    # Можно добавить другие профили
]

API_BASE_URL = "http://local.adspower.net:50325/api/v1"
TARGET_URL = "https://testnet.humanity.org/login"


class AdsProfile:
    def __init__(self, profile_id: str, metamask_password: str):
        self.profile_id = profile_id
        self.metamask_password = metamask_password
        self.browser = None
        self.page = None
        self.playwright = None

    def start_browser(self) -> Dict:
        """Запуск браузера через AdsPower API."""
        start_url = f"{API_BASE_URL}/browser/start?user_id={self.profile_id}"
        response = requests.get(start_url)
        response_data = response.json()
        if response_data["code"] != 0:
            raise Exception(f"Ошибка запуска браузера для профиля {self.profile_id}: {response_data['msg']}")
        return response_data["data"]

    async def find_metamask_window(self):
        """Поиск окна MetaMask среди открытых страниц браузера."""
        if not self.browser:
            return None
        for context in self.browser.contexts:
            for page in context.pages:
                if "chrome-extension://" in page.url:
                    return page
        return None

    async def initialize_metamask(self, metamask_window):
        """
        Разблокировка MetaMask:
          - Ввод пароля в поле (XPath: //input[@id='password'])
          - Нажатие кнопки разблокировки (XPath: //*[@id="app-content"]/div/div/div/div/button)
        """
        if not metamask_window:
            print(f"Профиль {self.profile_id}: Окно MetaMask не найдено")
            return False
        try:
            await metamask_window.bring_to_front()
            password_field = await metamask_window.query_selector("xpath=//input[@id='password']")
            if password_field:
                await password_field.fill(self.metamask_password)
                print(f"Профиль {self.profile_id}: Пароль введён")
            else:
                print(f"Профиль {self.profile_id}: Поле для пароля не найдено")
                return False

            await asyncio.sleep(2)
            unlock_button_xpath = "//*[@id='app-content']/div/div/div/div/button"
            unlock_button = await metamask_window.query_selector(f"xpath={unlock_button_xpath}")
            if unlock_button:
                await unlock_button.click()
                print(f"Профиль {self.profile_id}: MetaMask разблокирован")
                await asyncio.sleep(3)
                return True
            else:
                print(f"Профиль {self.profile_id}: Кнопка разблокировки не найдена")
                return False
        except Exception as e:
            print(f"Профиль {self.profile_id}: Ошибка при разблокировке MetaMask: {e}")
            return False

    async def initialize(self, playwright):
        """
        Последовательная инициализация профиля:
          Шаг 1. Запуск браузера через AdsPower API и переход на сайт.
          Шаг 2. Сначала пробуем нажать кнопку CONNECT WALLET. Если её нет, пробуем SKIP. Если и её нет – ищем кнопку вознаграждения
                   (текст которой может содержать слово GENESIS для CLAIM GENESIS REWARD или иначе – CLAIM DAILY REWARD) и кликаем по ней.
          Шаг 3. Если окно MetaMask не появилось автоматически, нажимаем кнопку MetaMask, ищем окно повторно и, если найдено,
                   разблокируем его. Затем повторно нажимаем кнопку CLAIM и подтверждаем действие.
          Шаг 4. Если кнопка SIGN MESSAGE найдена – кликаем по ней, иначе переходим к подтверждению через MetaMask.
          Шаг 5. Для вознаграждения повторно нажимаем кнопку CLAIM, выполняем разблокировку (если требуется) и нажимаем кнопку подтверждения.
                   Если разблокивать не надо, просто подтверждаем столько раз, сколько появляется окно MetaMask.
        """
        try:
            self.playwright = playwright
            browser_data = self.start_browser()
            self.browser = await playwright.chromium.connect_over_cdp(f"http://{browser_data['ws']['selenium']}")
            context = self.browser.contexts[0]
            self.page = context.pages[0]

            # Шаг 1. Переход на сайт
            await self.page.goto(TARGET_URL, timeout=60000)
            await self.page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)

            # Шаг 2. Пытаемся нажать CONNECT WALLET
            try:
                await self.page.wait_for_selector(f"xpath={CONNECT_WALLET_XPATH}", timeout=5000)
                await self.page.click(f"xpath={CONNECT_WALLET_XPATH}")
                print(f"Профиль {self.profile_id}: Нажата кнопка CONNECT WALLET")
                await asyncio.sleep(3)
            except Exception:
                print(f"Профиль {self.profile_id}: Кнопка CONNECT WALLET не найдена")
                # Если нет CONNECT WALLET – пробуем SKIP
                try:
                    await self.page.wait_for_selector(f"xpath={SKIP_BUTTON_XPATH}", timeout=5000)
                    await self.page.click(f"xpath={SKIP_BUTTON_XPATH}")
                    print(f"Профиль {self.profile_id}: Нажата кнопка SKIP")
                    await asyncio.sleep(2)
                except Exception:
                    print(f"Профиль {self.profile_id}: Кнопка SKIP не найдена, ищем кнопку вознаграждения")
                    # Ищем кнопку вознаграждения (CLAIM DAILY или GENESIS REWARD)
                    reward_button = await self.page.wait_for_selector(f"xpath={REWARD_XPATH}", timeout=30000)
                    reward_text = await reward_button.inner_text()
                    if "GENESIS" in reward_text.upper():
                        print(f"Профиль {self.profile_id}: Обнаружена кнопка CLAIM GENESIS REWARD")
                    else:
                        print(f"Профиль {self.profile_id}: Обнаружена кнопка CLAIM DAILY REWARD")
                    await reward_button.click()
                    print(f"Профиль {self.profile_id}: Нажата кнопка вознаграждения")
                    await asyncio.sleep(3)

            # Шаг 3. Проверяем, появилось ли окно MetaMask
            metamask_window = await self.find_metamask_window()
            if not metamask_window:
                # Если окно не появилось, нажимаем кнопку MetaMask
                await self.page.wait_for_selector(f"xpath={METAMASK_BUTTON_XPATH}", timeout=30000)
                await self.page.click(f"xpath={METAMASK_BUTTON_XPATH}")
                print(f"Профиль {self.profile_id}: Нажата кнопка MetaMask")
                await asyncio.sleep(3)
                metamask_window = await self.find_metamask_window()

            if not metamask_window:
                print(f"Профиль {self.profile_id}: Окно MetaMask не найдено")
                return False

            # Разблокировка MetaMask
            if not await self.initialize_metamask(metamask_window):
                print(f"Профиль {self.profile_id}: Ошибка разблокировки MetaMask")
                return False

            # После разблокировки нажимаем кнопку CLAIM еще раз и подтверждаем
            try:
                reward_button = await self.page.wait_for_selector(f"xpath={REWARD_XPATH}", timeout=30000)
                await reward_button.click()
                print(f"Профиль {self.profile_id}: Повторно нажата кнопка CLAIM")
                await asyncio.sleep(3)
            except Exception as e:
                print(f"Профиль {self.profile_id}: Ошибка при повторном нажатии CLAIM: {e}")

            # Шаг 4. Пытаемся нажать SIGN MESSAGE
            try:
                await self.page.wait_for_selector(f"xpath={SIGN_MESSAGE_BUTTON_XPATH}", timeout=5000)
                await self.page.click(f"xpath={SIGN_MESSAGE_BUTTON_XPATH}")
                print(f"Профиль {self.profile_id}: Нажата кнопка SIGN MESSAGE")
                await asyncio.sleep(3)
            except Exception:
                print(f"Профиль {self.profile_id}: Кнопка SIGN MESSAGE не найдена, переходим к подтверждению через MetaMask")

            # Шаг 5. Для вознаграждения: повторное подтверждение через MetaMask
            # Повторяем, пока окно MetaMask появляется (например, может быть несколько подтверждений)
            for attempt in range(3):
                metamask_window = await self.find_metamask_window()
                if metamask_window:
                    print(f"Профиль {self.profile_id}: MetaMask окно обнаружено для подтверждения (попытка {attempt+1})")
                    # Если требуется, пробуем разблокировать (если окно требует ввода пароля)
                    if not await self.initialize_metamask(metamask_window):
                        print(f"Профиль {self.profile_id}: Ошибка разблокировки MetaMask при подтверждении, пробуем подтвердить без разблокировки")
                    try:
                        await metamask_window.wait_for_selector(f"xpath={CONFIRM_CLAIM_XPATH}", timeout=10000)
                        await metamask_window.click(f"xpath={CONFIRM_CLAIM_XPATH}")
                        print(f"Профиль {self.profile_id}: Подтверждение в MetaMask выполнено")
                    except Exception as e:
                        print(f"Профиль {self.profile_id}: Ошибка при подтверждении в MetaMask: {e}")
                    await asyncio.sleep(3)
                else:
                    print(f"Профиль {self.profile_id}: Окно MetaMask не найдено для повторного подтверждения")
                    break

            return True

        except Exception as e:
            print(f"Профиль {self.profile_id}: Ошибка при инициализации: {e}")
            return False


async def main():
    profiles = [AdsProfile(p["profile_id"], p["metamask_password"]) for p in PROFILES]
    async with async_playwright() as playwright:
        for profile in profiles:
            success = await profile.initialize(playwright)
            if not success:
                print(f"Профиль {profile.profile_id}: Инициализация не удалась, пропускаем")
            else:
                print(f"Профиль {profile.profile_id}: Успешно инициализирован")
            await asyncio.sleep(5)
        # Закрытие браузеров
        for profile in profiles:
            if profile.browser:
                await profile.browser.close()

if __name__ == "__main__":
    asyncio.run(main())