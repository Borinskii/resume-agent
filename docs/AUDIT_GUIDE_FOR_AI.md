# Инструкция для AI: как делать настоящий audit веб-приложения

## Главное правило: «работает» = я кликнул кнопку → проверил результат, а не «URL открылся 200»

URL вернувший 200 OK ≠ работающая фича. Title `<title>` правильный ≠ страница рендерит контент. Кнопка существует в DOM ≠ она кликабельна и делает что должна. Нужно **реально кликать, заполнять, submit'ить и проверять результат** в БД / toast / редиректе.

---

## Чек-листы по типам элементов

### CRUD-ресурс (любой список с Create/Read/Update/Delete)

Для каждого ресурса (например `/admin/clients`, `/admin/slots`) пройти все шаги:

1. **List**: открыть, проверить что rows > 0 (или показано «нет данных» если пусто). Прочитать `tbody tr` count.
2. **Search**: ввести существующий term → rows должно уменьшиться. Очистить → восстановиться.
3. **Каждый фильтр** (select / checkbox / date):
   - Применить → rows count меняется → запомнить
   - Сбросить → rows возвращаются к исходному
   - Скомбинировать несколько фильтров
4. **Sort columns**: кликнуть каждый header (если sortable) → проверить порядок изменился
5. **Pagination**: переключить 5/10/25/50/All, кликнуть «Next», «Prev», «Last»
6. **Create form**:
   - Open create page → проверить **все** видимые поля
   - Submit пустую форму → должны появиться **видимые validation errors** на каждом required поле
   - Заполнить **только обязательные** → submit → проверить редирект + toast «Создано»
   - Verify в БД (через tinker / API) что запись реально появилась с правильными значениями
   - Заполнить **с невалидными данными** (invalid email, short password, future date в past field) → должны быть field-level errors
7. **Edit form**:
   - Open `/edit/{id}` → все поля предзаполнены данными
   - Изменить одно поле → Save → toast → проверить в БД что значение обновлено
   - Edit и Cancel → значения не должны сохраниться
8. **Delete**:
   - Кликнуть «Удалить» → должен открыться confirm modal
   - Cancel → запись осталась
   - Confirm → запись удалена + toast «Удалено» + rows count -1

### Action button с modal

1. Кликнуть кнопку → проверить что модал реально открылся (а не просто DOM создался)
2. Прочитать содержимое модала через `document.querySelector('.fi-modal-window')?.innerText`
3. Проверить что заголовок и поля соответствуют ожиданиям
4. Заполнить **все** поля валидными значениями
5. Заполнить с **невалидными** значениями → должны быть видимые errors
6. Submit → проверить:
   - Toast notification (через `document.querySelectorAll('[role=status]')`)
   - Изменение в основном списке (status badge, removed action button, etc.)
   - Запись в БД (action / audit_log / другой эффект)
7. Открыть модал снова → Cancel/Close → проверить что ничего не сохранилось

### Табы внутри страницы (Filament edit, Livewire tab UI)

1. Кликнуть **каждый** таб по очереди
2. После каждого клика **прочитать DOM** (не `[role=tabpanel]` — Filament использует Alpine x-show, а ищи по тексту через `document.querySelector('main')?.innerText`)
3. Проверить что **содержимое таба содержит ожидаемые данные** клиента (имя, адрес, серийник, и т.д.) — не просто заголовки «Адреса»
4. Если в табе есть форма — заполнить, сохранить, перепроверить
5. Если в табе есть ссылка (e.g. «открыть фото паспорта») — кликнуть, проверить открывается

### Sidebar / Navigation menu

1. Перечислить **все** ссылки sidebar через `document.querySelectorAll('aside a, nav a')`
2. Кликнуть **каждую** → проверить что:
   - URL изменился на ожидаемый
   - Title новой страницы соответствует
   - Active state в sidebar сместился (highlighted)
   - Контент **реально** загрузился (не 500 / not blank)
3. Если ссылка ведёт на placeholder с надписью «Phase X» / «Coming soon» — **это баг**, надо удалять или делать рабочей
4. Если href="#" — **это баг** (мёртвая ссылка)

### Auth flows

1. **Register**:
   - Шаг 1: пустая форма → validation errors
   - Шаг 1: валидные данные → переход на шаг 2
   - Шаг 2: неверный SMS код → error «неверный код»
   - Шаг 2: получить код из логов → переход на шаг 3
   - Шаг 3: пароли не совпадают → error
   - Шаг 3: валидно → auto-login → в кабинет
2. **Login**:
   - Неверный пароль → error «неверные учётные данные»
   - Заблокированный аккаунт → специальный error
   - Валидный → редирект в /cabinet или /admin
3. **Forgot password**: полный цикл телефон → SMS → код → новый пароль → auto-login
4. **Logout**: реально выйти + проверить что `/cabinet` теперь редиректит на /login
5. **2FA setup**: QR-код виден → ввести OTP → редирект в /admin
6. **2FA challenge** (на втором входе): попасть на challenge page → ввести OTP → /admin

### Лендинг (если есть)

1. Прокликать **каждую** видимую CTA-кнопку → проверить редирект
2. Если есть формы сбора lead'ов — заполнить, submit, проверить куда улетел
3. Якорные ссылки (#section) — кликнуть, проверить scroll
4. Tel:/mailto: ссылки — кликнуть, проверить protocol handler

---

## Конкретные техники для Chrome MCP / browser automation

### 1. **Реальный клик через computer.left_click**, а не `element.click()`

JS-click от программы часто **не вызывает** обработчики через capture phase, не запускает Alpine/Livewire реакции. Используй MCP `computer` action `left_click` по `ref_N` из `find` / `read_page`.

```
"name": "computer",
"input": {"action": "left_click", "ref": "ref_29", "tabId": 12345}
```

### 2. **Чтение DOM после клика** через таймаут

После клика Livewire/Alpine нужны 500-1500ms на reactive update. Делай `await new Promise(r => setTimeout(r, 1500))` перед чтением результата.

### 3. **Поиск visible modal**

Filament оставляет в DOM пустые модалы. Ищи **видимый и непустой**:

```js
const modal = Array.from(document.querySelectorAll('.fi-modal-window')).find(m => {
  const s = getComputedStyle(m);
  return s.display !== 'none' && m.offsetParent !== null && (m.innerText || '').trim().length > 0;
});
```

### 4. **Toast notification**

```js
const toasts = Array.from(document.querySelectorAll('[role=status], .fi-no-notification'))
  .map(e => e.innerText.trim())
  .filter(Boolean);
```

### 5. **Validation errors**

```js
const errors = Array.from(document.querySelectorAll('.fi-fo-field-wrp-error-message, [data-validation-error], .text-red-600'))
  .map(e => e.innerText.trim())
  .filter(Boolean);
```

### 6. **Tab content** — НЕ через `[role=tabpanel]`

Filament Tabs использует Alpine `x-show`. Все панели в DOM, скрыты CSS. Чтобы прочитать активный таб — кликни таб + читай `document.querySelector('main')?.innerText`.

### 7. **Filament Select / Combobox**

Это не `<select>`, а Choices.js / custom-component. Чтобы выбрать:
- Click на видимое поле → откроется dropdown
- Click на нужный `<option role="option">`
- НЕ пытайся `select.value = X` напрямую — это не сработает

### 8. **Livewire `$wire.set()` метод**

В Livewire 3 НЕТ метода `$wire.set(prop, value)`. Только:
- Прямое присваивание: `c.$wire.propName = 'value'`
- Или через DOM event на input с `wire:model`

### 9. **Logout + clean session**

После logout JS `document.cookie = ...; expires=...` **не удаляет httponly cookies** типа session/remember. Нужно либо:
- POST на `/logout` через form: `fetch(form.action, { method: 'POST', body: new FormData(form), credentials: 'include' })`
- Или открыть инкогнито-окно

### 10. **httponly cookies могут вернуть тебя залогиненным**

После `truncate sessions` в БД — браузерные cookies остаются. Cookie с remember_token reauthenticate user. Если тестируешь как guest — **обязательно** обнули `remember_token` у всех users в БД:

```php
DB::table('users')->update(['remember_token' => null]);
DB::table('sessions')->truncate();
```

### 11. **Page may redirect after action via Livewire $this->redirect()**

В Livewire 3 `$this->redirect()` асинхронный. Подожди 1500-2000ms после click и потом читай `window.location.pathname`.

---

## Filament-specific гочи (если используется Filament)

| Симптом | Причина | Фикс |
|---------|---------|------|
| `Undefined variable $slot` | Layout использует Livewire `$slot`, а child использует Blade `@extends/@yield` | Поддержать оба в layout: `{{ $slot ?? '' }} @hasSection('content') @yield('content') @endif` |
| `Call to charges() on null` в filter | `$query->whereHas('relation', ...)` иногда падает в Filament context | Заменить на `$query->whereExists(fn ($sub) => $sub->select(DB::raw(1))->from('charges')->whereColumn('charges.user_id', 'users.id')->where(...))` |
| Modal не открывается через ref после reload | Filament reindex'ит refs — нужен новый `find` после navigate | Перевызвать `find` после каждого navigate/action |
| Filter `query()` callback падает с `$q is unresolvable` | Filament резолвит параметры **по имени**, не позиции | Использовать имя `$query` или type-hint `Builder $query` |
| `Target [EnumClass] is not instantiable` | Filament пытается DI-инжектить enum в `formatStateUsing(fn (?MyEnum $s) => ...)` | Заменить на `->state(fn ($record) => $record->field?->value)` |
| Validation error в form action не показывается | Throw RuntimeException = 500. Должен быть `ValidationException::withMessages([...])` | Заменить `throw new RuntimeException` на `throw ValidationException::withMessages(['field' => ['msg']])` |

---

## Что проверять в БД после каждого action

После любого submit / action:

```php
php artisan tinker --execute='
// Что должно было создаться?
$lastRecord = App\Models\X::latest()->first();
echo "id=" . $lastRecord->id . " field1=" . $lastRecord->field1 . PHP_EOL;

// Audit log должен иметь запись?
$lastAudit = App\Models\AuditLog::latest()->first();
echo $lastAudit->action . " | " . json_encode($lastAudit->payload);
'
```

Не верь только toast'у — проверь БД.

---

## Когда говорить «работает» а когда «есть баг»

| Ситуация | Это работает? |
|----------|---------------|
| URL отдал 200 + правильный title | ❌ Нет. Title правильный, но контент может быть пустой. |
| DOM содержит кнопку с правильным текстом | ❌ Нет. Кнопка может быть размером 0×0 / скрыта CSS. |
| После клика кнопки страница не сменилась | ❌ Скорее всего баг. Должен быть toast / redirect / state change. |
| Toast «Создано» + редирект на /edit/{id} | ✅ Работает. Проверь ещё БД для уверенности. |
| Modal открылся но кнопки в нём не нажимаются | ❌ Баг. Кнопки должны быть кликабельны. |
| Sidebar ссылка ведёт на `href="#"` | ❌ Мёртвая ссылка. Удалить или сделать рабочей. |
| Страница содержит фразу «Phase X», «Coming soon», «TODO» | ❌ Это не production-ready. Заменить на реальный функционал ИЛИ удалить. |
| Validation error на английском когда UI на русском | ⚠️ Незакрытый i18n. Низкий приоритет, но не должно быть в проде. |
| InvalidArgumentException / RuntimeException → 500 на форме | ❌ Должен быть ValidationException → field error. |

---

## Структура финального отчёта

После audit пиши отчёт в формате таблицы. Никакой воды.

```markdown
## Что прокликано (admin)

| Resource | Action | Result |
|----------|--------|--------|
| /admin/clients | Filter "Только просроченные" | ✅ rows 10→2 |
| /admin/clients | Approve modal (id=6) | ✅ toast "Клиент одобрен", status→approved |
| /admin/clients | Edit 7 tabs | ✅ все рендерят реальные данные клиента |
| /admin/installation-slots | Create slot | ✅ id=N, redirect /edit |
| /admin/installation-slots | Delete slot | ✅ confirm → rows -1 |
| /admin/charges | Принять платёж modal | ✅ Payment id=N saved, toast |
| ... | ... | ... |

## Что прокликано (client cabinet)

| Page | Action | Result |
|------|--------|--------|
| /cabinet | Status badge + progress | ✅ 6/6 |
| /cabinet/billing | Promise modal "С 10-го по 20-е" | ✅ toast "Спасибо!" |
| /cabinet/settings/notifications | Toggle SMS off | ✅ persisted |
| ... | ... | ... |

## Найденные баги (если есть)

| # | Что | Где | Severity | Status |
|---|-----|-----|----------|--------|
| 1 | ... | ... | high | ✅ fixed |
| 2 | ... | ... | medium | ⚠️ deferred |

## БД verifications

`php artisan tinker --execute='...'` — проверены 9 объектов реально появились/изменились:
- slot id=6 created with cap=3 → deleted
- payment id=3 with amount 5.00
- contract template v2 activated, v1 deactivated
- ...

## Что НЕ прокликано (явно)

- Bulk Create N slots с reverse order — не критично
- File upload (паспорт) — MCP не умеет file upload, проверено через tinker
- 2FA recovery codes flow — отдельный sub-flow
```

---

## TL;DR — три правила

1. **Не доверяй URL/title** — читай DOM текст активной страницы после действия
2. **Не доверяй toast'у** — проверяй БД через tinker (запись реально создана / обновлена / удалена)
3. **Клики через `computer.left_click` с ref**, не через JS `.click()` — DOM-программные клики часто не запускают Alpine/Livewire реакции

Если этим правилам следовать — найдёшь все баги. Если ленишься и проверяешь только URL → пропустишь 80% багов и получишь от заказчика «у меня не работает X», когда уже после демо.
