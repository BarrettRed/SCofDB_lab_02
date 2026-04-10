# План отчёта для защиты лабораторной работы №2
## Управление конкурентными транзакциями в маркетплейсе

---

## 📋 Структура защиты (15-20 минут)

### Часть 1: Введение (2-3 минуты)

#### 1.1. Постановка проблемы
**Ключевой вопрос:** Что такое race condition и почему это опасно?

**Тезисы для ответа:**
- Race condition — ситуация, когда результат зависит от порядка выполнения параллельных транзакций
- В маркетплейсе: двойная оплата, овербукинг товаров, некорректные балансы
- Финансовые потери, репутационные риски, недовольные клиенты

**Пример для демонстрации:**
```
Пользователь дважды нажал "Оплатить" → два HTTP-запроса → 
две параллельные транзакции → заказ оплачен дважды → 
списано 2× суммы, отправлено 2× товара
```

#### 1.2. Цель работы
- Продемонстрировать race condition на практике
- Показать, как уровни изоляции СУБД решают проблему
- Реализовать и протестировать два подхода: безопасный и небезопасный

---

### Часть 2: Теоретическая часть (3-4 минуты)

#### 2.1. Уровни изоляции транзакций (SQL Standard)

| Уровень | Dirty Read | Non-Repeatable Read | Phantom Read |
|---------|------------|---------------------|--------------|
| READ UNCOMMITTED | ❌ | ❌ | ❌ |
| READ COMMITTED | ✅ | ❌ | ❌ |
| REPEATABLE READ | ✅ | ✅ | ✅* |
| SERIALIZABLE | ✅ | ✅ | ✅ |

_*В PostgreSQL REPEATABLE READ предотвращает phantom reads благодаря MVCC_

#### 2.2. Почему READ COMMITTED не защищает?

**Механизм работы:**
- Каждый `SELECT` видит snapshot на момент **начала запроса**
- Между двумя `SELECT` в одной транзакции другая транзакция может сделать `COMMIT`
- Второй `SELECT` увидит **изменённые данные**

**Демонстрация проблемы:**
```sql
-- Сессия 1                          -- Сессия 2
BEGIN;                               BEGIN;
SELECT status FROM orders            SELECT status FROM orders
WHERE id = '...';  -- 'created'      WHERE id = '...';  -- 'created'
                                     -- ОБЕ видят 'created'!
UPDATE orders SET status = 'paid'    
WHERE id = '...';                    -- ЖДЁТ блокировки
COMMIT;                              -- Сессия 1 освободила
                                     UPDATE orders SET status = 'paid'
                                     WHERE id = '...';  -- УСПЕХ!
                                     COMMIT;
-- ИТОГ: ДВЕ записи в истории!
```

#### 2.3. Механизмы блокировок

**FOR UPDATE:**
- Эксклюзивная блокировка строки
- Другие транзакции ждут освобождения
- Предотвращает concurrent UPDATE/DELETE

**Типы блокировок:**
```sql
FOR UPDATE      -- Эксклюзивная (никто не может изменить)
FOR SHARE       -- Разделяемая (можно читать, нельзя менять)
FOR NO KEY UPDATE -- Как UPDATE, но разрешает FOR KEY SHARE
FOR KEY SHARE   -- Слабая (защита от DELETE ключевых полей)
```

---

### Часть 3: Практическая реализация (5-6 минут)

#### 3.1. Архитектура решения

```
┌─────────────────────────────────────────────────────────┐
│                    Backend (FastAPI)                     │
├─────────────────────────────────────────────────────────┤
│  app/application/payment_service.py                      │
│  ├── pay_order_unsafe()  → READ COMMITTED (без защиты)  │
│  └── pay_order_safe()    → REPEATABLE READ + FOR UPDATE │
├─────────────────────────────────────────────────────────┤
│  app/tests/                                              │
│  ├── test_concurrent_payment_unsafe.py  → 2 оплаты ❌   │
│  └── test_concurrent_payment_safe.py    → 1 оплата ✅   │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│              PostgreSQL 16 (marketplace)                 │
│  ├── orders                                             │
│  ├── order_status_history                               │
│  └── TRIGGER: check_order_not_already_paid()            │
└─────────────────────────────────────────────────────────┘
```

#### 3.2. Код: pay_order_unsafe()

```python
async def pay_order_unsafe(self, order_id: UUID) -> dict:
    async with self.session.begin():
        # Чтение БЕЗ блокировки (READ COMMITTED)
        status = await self.session.execute(
            text("SELECT status FROM orders WHERE id = :order_id"),
            {"order_id": order_id}
        )
        status = status.first()[0]
        
        if status != 'created':
            raise OrderAlreadyPaidError()
        
        # UPDATE без защиты от конкурентности
        await self.session.execute(
            text("UPDATE orders SET status = 'paid' WHERE id = :order_id"),
            {"order_id": order_id}
        )
        
        # Запись в историю
        await self.session.execute(
            text("INSERT INTO order_status_history (...) VALUES (...)")
        )
    
    return {"order_id": order_id, "status": "paid"}
```

**Проблема:** Между `SELECT` и `UPDATE` другая транзакция может сделать то же самое.

#### 3.3. Код: pay_order_safe()

```python
async def pay_order_safe(self, order_id: UUID) -> dict:
    async with self.session.begin():
        # 1. Устанавливаем REPEATABLE READ
        await self.session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        )
        
        # 2. Блокируем строку FOR UPDATE
        status = await self.session.execute(
            text("SELECT status FROM orders WHERE id = :order_id FOR UPDATE"),
            {"order_id": order_id}
        )
        status = status.first()[0]
        
        if status != 'created':
            raise OrderAlreadyPaidError()
        
        # 3. UPDATE (строка уже заблокирована)
        await self.session.execute(
            text("UPDATE orders SET status = 'paid' WHERE id = :order_id")
        )
        
        # 4. Запись в историю
        await self.session.execute(
            text("INSERT INTO order_status_history (...) VALUES (...)")
        )
    
    return {"order_id": order_id, "status": "paid"}
```

**Решение:** `FOR UPDATE` блокирует строку, другие транзакции ждут.

#### 3.4. Тесты: демонстрация проблемы

**test_concurrent_payment_unsafe.py:**
```python
async def test_concurrent_payment_unsafe_demonstrates_race_condition(...):
    # Запускаем 2 параллельных оплаты
    results = await asyncio.gather(
        payment_attempt_1(),  # pay_order_unsafe()
        payment_attempt_2(),  # pay_order_unsafe()
        return_exceptions=True
    )
    
    # Проверяем историю
    history = await service.get_payment_history(order_id)
    
    # ОЖИДАЕМ: 2 записи 'paid' (RACE CONDITION!)
    assert len(history) == 2
    print("⚠️ RACE CONDITION DETECTED!")
```

#### 3.5. Тесты: демонстрация решения

**test_concurrent_payment_safe.py:**
```python
async def test_concurrent_payment_safe_prevents_race_condition(...):
    # Запускаем 2 параллельных оплаты
    results = await asyncio.gather(
        payment_attempt_1(),  # pay_order_safe()
        payment_attempt_2(),  # pay_order_safe()
        return_exceptions=True
    )
    
    # Проверяем результаты
    success_count = sum(1 for r in results if not isinstance(r, Exception))
    error_count = sum(1 for r in results if isinstance(r, Exception))
    
    # ОЖИДАЕМ: 1 успех, 1 ошибка
    assert success_count == 1
    assert error_count == 1
    
    # Проверяем историю: только 1 запись
    history = await service.get_payment_history(order_id)
    assert len(history) == 1
    print("✅ RACE CONDITION PREVENTED!")
```

---

### Часть 4: Результаты тестирования (2-3 минуты)

#### 4.1. Демонстрация race condition

**Запуск теста:**
```bash
docker-compose exec backend pytest app/tests/test_concurrent_payment_unsafe.py -v -s
```

**Ожидаемый вывод:**
```
test_concurrent_payment_unsafe_demonstrates_race_condition PASSED
⚠️ RACE CONDITION DETECTED!
Order <uuid> was paid TWICE:
  - 2026-03-27 18:31:24: status = paid
  - 2026-03-27 18:31:24: status = paid
```

**Что произошло:**
1. Обе транзакции прочитали `status = 'created'`
2. Обе выполнили `UPDATE` (вторая ждала первую)
3. Обе записали в историю → **двойная оплата**

#### 4.2. Демонстрация решения

**Запуск теста:**
```bash
docker-compose exec backend pytest app/tests/test_concurrent_payment_safe.py -v -s
```

**Ожидаемый вывод:**
```
test_concurrent_payment_safe_prevents_race_condition PASSED
✅ RACE CONDITION PREVENTED!
Order <uuid> was paid only ONCE:
  - 2026-03-27 18:31:29: status = paid
Second attempt was rejected: OrderAlreadyPaidError(...)
```

**Что произошло:**
1. Первая транзакция заблокировала строку (`FOR UPDATE`)
2. Вторая транзакция ждала освобождения
3. Первая завершилась, статус стал `'paid'`
4. Вторая прочитала `'paid'` → выбросила `OrderAlreadyPaidError`

---

### Часть 5: Анализ и рекомендации (3-4 минуты)

#### 5.1. Сравнение подходов

| Критерий | READ COMMITTED (unsafe) | REPEATABLE READ + FOR UPDATE (safe) |
|----------|-------------------------|-------------------------------------|
| Производительность | Высокая | Средняя (блокировки) |
| Безопасность | ❌ Race condition | ✅ Полная защита |
| Сложность | Простой | Требует явных блокировок |
| Use case | Чтение, аналитика | Финансовые операции |

#### 5.2. Рекомендации для продакшена

**Гибридный подход:**

1. **Default: READ COMMITTED** (95% операций)
   - Просмотр каталога
   - История заказов
   - Профиль пользователя

2. **REPEATABLE READ + FOR UPDATE** (5% операций)
   - Оплата заказа
   - Изменение баланса
   - Резервирование товара

3. **Дополнительно: Optimistic Locking**
   - Обновление счётчиков
   - Рейтинги товаров

**Пример кода для продакшена:**
```python
async def pay_order(order_id: UUID):
    async with db.transaction(isolation='repeatable_read'):
        # Блокируем заказ
        order = await db.fetch_one(
            "SELECT * FROM orders WHERE id = $1 FOR UPDATE",
            order_id
        )
        
        if order['status'] != 'created':
            raise OrderAlreadyPaidError()
        
        # Обновляем статус
        await db.execute(
            "UPDATE orders SET status = 'paid' WHERE id = $1",
            order_id
        )
        
        # Записываем в историю
        await db.execute(
            "INSERT INTO order_status_history (...) VALUES (...)"
        )
```

#### 5.3. Альтернативные подходы

**1. SERIALIZABLE везде:**
- ✅ Максимальная безопасность
- ❌ Снижение производительности (20-50%)
- ❌ Требует retry logic

**2. Optimistic Locking (версионирование):**
```sql
ALTER TABLE orders ADD COLUMN version INTEGER DEFAULT 1;

UPDATE orders
SET status = 'paid', version = version + 1
WHERE id = '...' AND status = 'created' AND version = 1;

-- Проверить ROW_COUNT, если 0 — конфликт
```

**3. Advisory Locks:**
```sql
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('order_' || order_id));
-- Критическая секция
COMMIT;
```

---

### Часть 6: Заключение (1-2 минуты)

#### 6.1. Выводы

1. **READ COMMITTED не защищает** от race condition при конкурентных операциях
2. **REPEATABLE READ + FOR UPDATE** решает проблему через блокировки
3. **Без FOR UPDATE** даже REPEATABLE READ не гарантирует корректность
4. **Для продакшена** рекомендуется гибридный подход

#### 6.2. Что было сделано

- ✅ Реализованы два метода оплаты (unsafe/safe)
- ✅ Написаны тесты, демонстрирующие проблему и решение
- ✅ Заполнен отчёт с теоретическим обоснованием
- ✅ Подготовлены рекомендации для продакшена

#### 6.3. Возможные улучшения

- Добавить retry logic для обработки deadlock
- Реализовать optimistic locking для счётчиков
- Добавить метрики производительности для сравнения

---

## 🎯 Вопросы для самопроверки

### Теоретические вопросы

1. **Что такое dirty read, non-repeatable read, phantom read?**
2. **Почему PostgreSQL на REPEATABLE READ предотвращает phantom reads?**
3. **В чём разница между FOR UPDATE и FOR SHARE?**
4. **Что такое serialization failure и как его обрабатывать?**
5. **Почему READ UNCOMMITTED в PostgreSQL работает как READ COMMITTED?**

### Практические вопросы

1. **Что произойдёт, если убрать FOR UPDATE из pay_order_safe()?**
2. **Почему тесты используют РАЗНЫЕ сессии для имитации запросов?**
3. **Как работает триггер check_order_not_already_paid()?**
4. **Может ли deadlock возникнуть при использовании FOR UPDATE?**
5. **Почему нельзя использовать SERIALIZABLE везде?**

### Вопросы по коду

1. **Зачем нужен `async with self.session.begin()`?**
2. **Почему `SET TRANSACTION ISOLATION LEVEL` выполняется внутри транзакции?**
3. **Что такое `return_exceptions=True` в `asyncio.gather()`?**
4. **Зачем фикстура `db_engine` отдельна от `db_session`?**
5. **Почему в тестах используется `ON CONFLICT DO NOTHING`?**

---

## 📊 Демонстрационные слайды (опционально)

### Слайд 1: Проблема
```
┌──────────────┐    ┌──────────────┐
│  Сессия 1    │    │  Сессия 2    │
│  SELECT      │    │              │
│  status='created' │              │
│              │    │  SELECT      │
│              │    │  status='created' │
│  UPDATE      │    │              │
│  status='paid' │    │              │
│  COMMIT      │    │  UPDATE      │
│              │    │  status='paid' │
│              │    │  COMMIT      │
└──────────────┘    └──────────────┘
         ↓                   ↓
    ✅ Успех           ✅ Успех (ПРОБЛЕМА!)
```

### Слайд 2: Решение
```
┌──────────────┐    ┌──────────────┐
│  Сессия 1    │    │  Сессия 2    │
│  SELECT      │    │              │
│  ...FOR UPDATE│    │              │
│  status='created' │              │
│              │    │  SELECT      │
│              │    │  ...FOR UPDATE │
│  UPDATE      │    │  (ЖДЁТ!)     │
│  status='paid' │    │              │
│  COMMIT      │    │  SELECT      │
│              │    │  status='paid' │
│              │    │  ERROR!      │
└──────────────┘    └──────────────┘
         ↓                   ↓
    ✅ Успех           ❌ Отказ (КОРРЕКТНО!)
```

### Слайд 3: Сравнение результатов
```
НЕБЕЗОПАСНО (READ COMMITTED):
┌────────────────────────────────┐
│ order_status_history           │
│ id | order_id | status | time  │
│ 1  | ...      | created | t1   │
│ 2  | ...      | paid    | t2   │ ← Сессия 1
│ 3  | ...      | paid    | t3   │ ← Сессия 2 ❌
└────────────────────────────────┘

БЕЗОПАСНО (REPEATABLE READ + FOR UPDATE):
┌────────────────────────────────┐
│ order_status_history           │
│ id | order_id | status | time  │
│ 1  | ...      | created | t1   │
│ 2  | ...      | paid    | t2   │ ← Сессия 1 ✅
│    |          |         |      │ ← Сессия 2 отклонена ✅
└────────────────────────────────┘
```

---

## 🔗 Полезные ссылки

- [PostgreSQL: Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- [PostgreSQL: Explicit Locking](https://www.postgresql.org/docs/current/explicit-locking.html)
- [SQLAlchemy: Async Session](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [AsyncPG: Connection](https://magicstack.github.io/asyncpg/current/api/index.html)

---

## 📝 Чек-лист перед защитой

- [ ] Запустить оба теста, убедиться, что проходят
- [ ] Подготовить скриншоты результатов тестов
- [ ] Повторить теорию (уровни изоляции, типы блокировок)
- [ ] Подготовить ответы на вопросы самопроверки
- [ ] Проверить, что отчёт REPORT.md заполнен полностью
- [ ] Убедиться, что код закоммичен в репозиторий

---

**Время доклада:** 15-20 минут  
**Время на вопросы:** 5-10 минут  
**Общее время:** 20-30 минут
