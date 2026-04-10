"""
Тест для демонстрации РЕШЕНИЯ проблемы race condition.

Этот тест должен ПРОХОДИТЬ, подтверждая, что при использовании
pay_order_safe() заказ оплачивается только один раз.
"""

import asyncpg
import asyncio
import pytest
import uuid
import time
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.application.payment_service import PaymentService
from app.domain.exceptions import OrderAlreadyPaidError


# TODO: Настроить подключение к тестовой БД
DATABASE_URL = "postgresql+asyncpg://postgres:postgres@db:5432/marketplace"


@pytest.fixture
async def db_session():
    """
    Создать сессию БД для тестов.
    
    TODO: Реализовать фикстуру (см. test_concurrent_payment_unsafe.py)
    """
    engine = create_async_engine(DATABASE_URL)
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()
    # TODO: Реализовать создание сессии
    #raise NotImplementedError("TODO: Реализовать db_session fixture")


@pytest.fixture
async def test_order(db_session):
    """
    Создать тестовый заказ со статусом 'created'.
    
    TODO: Реализовать фикстуру (см. test_concurrent_payment_unsafe.py)
    """
    user_id = uuid.uuid4()
    order_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO users (id, email, name) VALUES (:id, :email, :name)"),
        {'id': str(user_id), 'email': f'null_{user_id}@test.com', 'name': 'Test User'}
    )
    await db_session.execute(
        text("INSERT INTO orders (id, user_id, status, total_amount) VALUES (:id, :user_id, 'created', 100.0)"),
        {'id': str(order_id), 'user_id': str(user_id)}
    )
    await db_session.commit()
    yield order_id 

    await db_session.execute(text("DELETE FROM order_status_history WHERE order_id = :id"), {'id': str(order_id)})
    await db_session.execute(text("DELETE FROM orders WHERE id = :id"), {'id': str(order_id)})
    await db_session.execute(text("DELETE FROM users WHERE id = :id"), {'id': str(user_id)})
    await db_session.commit()
    # TODO: Реализовать создание тестового заказа
    #raise NotImplementedError("TODO: Реализовать test_order fixture")


@pytest.mark.asyncio
async def test_concurrent_payment_safe_prevents_race_condition(db_session, test_order):
    """
    Тест демонстрирует решение проблемы race condition с помощью pay_order_safe().
    
    ОЖИДАЕМЫЙ РЕЗУЛЬТАТ: Тест ПРОХОДИТ, подтверждая, что заказ был оплачен только один раз.
    Это показывает, что метод pay_order_safe() защищен от конкурентных запросов.
    
    TODO: Реализовать тест следующим образом:
    
    1. Создать два экземпляра PaymentService с РАЗНЫМИ сессиями
       (это имитирует два независимых HTTP-запроса)
       
    2. Запустить два параллельных вызова pay_order_safe():
       
       async def payment_attempt_1():
           service1 = PaymentService(session1)
           return await service1.pay_order_safe(order_id)
           
       async def payment_attempt_2():
           service2 = PaymentService(session2)
           return await service2.pay_order_safe(order_id)
           
       results = await asyncio.gather(
           payment_attempt_1(),
           payment_attempt_2(),
           return_exceptions=True
       )
       
    3. Проверить результаты:
       - Одна попытка должна УСПЕШНО завершиться
       - Вторая попытка должна выбросить OrderAlreadyPaidError ИЛИ вернуть ошибку
       
       success_count = sum(1 for r in results if not isinstance(r, Exception))
       error_count = sum(1 for r in results if isinstance(r, Exception))
       
       assert success_count == 1, "Ожидалась одна успешная оплата"
       assert error_count == 1, "Ожидалась одна неудачная попытка"
       
    4. Проверить историю оплат:
       
       service = PaymentService(session)
       history = await service.get_payment_history(order_id)
       
       # ОЖИДАЕМ ОДНУ ЗАПИСЬ 'paid' - проблема решена!
       assert len(history) == 1, "Ожидалась 1 запись об оплате (БЕЗ RACE CONDITION!)"
       
    5. Вывести информацию об успешном решении:
       
       print(f"✅ RACE CONDITION PREVENTED!")
       print(f"Order {order_id} was paid only ONCE:")
       print(f"  - {history[0]['changed_at']}: status = {history[0]['status']}")
       print(f"Second attempt was rejected: {results[1]}")
    """
    order_id = test_order
    engine = create_async_engine(DATABASE_URL)

    async def payment_attempt_1():
        async with AsyncSession(engine) as session1:
            service1 = PaymentService(session1)
            return await service1.pay_order_safe(order_id)  # RR+FU
    async def payment_attempt_2():
        async with AsyncSession(engine) as session2:
            service2 = PaymentService(session2)
            return await service2.pay_order_safe(order_id)
    results = await asyncio.gather(
        payment_attempt_1(),
        payment_attempt_2(),
        return_exceptions=True
    )
    await engine.dispose()

    success_count = sum(1 for r in results if not isinstance(r, Exception))
    error_count = sum(1 for r in results if isinstance(r, Exception))
    assert success_count == 1
    assert error_count == 1
    
    history = await PaymentService(db_session).get_payment_history(order_id)
    assert len(history) == 1

    print(f"✅ RACE CONDITION PREVENTED!")
    print(f"Order {order_id} was paid only ONCE:")
    print(f"  - {history[0]['changed_at']}: status = {history[0]['status']}")
    print(f"Second attempt was rejected: {results[1]}")
    # TODO: Реализовать тест, демонстрирующий решение race condition
    #raise NotImplementedError("TODO: Реализовать test_concurrent_payment_safe")


@pytest.mark.asyncio
async def test_concurrent_payment_safe_with_explicit_timing():
    """
    Дополнительный тест: проверить работу блокировок с явной задержкой.
    
    TODO: Реализовать тест с добавлением задержки в первой транзакции:
    
    1. Первая транзакция:
       - Начать транзакцию
       - Заблокировать заказ (FOR UPDATE)
       - Добавить задержку (asyncio.sleep(1))
       - Оплатить
       - Commit
       
    2. Вторая транзакция (запустить через 0.1 секунды после первой):
       - Начать транзакцию
       - Попытаться заблокировать заказ (FOR UPDATE)
       - ДОЛЖНА ЖДАТЬ освобождения блокировки от первой транзакции
       - После освобождения - увидеть обновленный статус 'paid'
       - Выбросить OrderAlreadyPaidError
       
    3. Проверить временные метки:
       - Вторая транзакция должна завершиться ПОЗЖЕ первой
       - Разница должна быть >= 1 секунды (время задержки)
       
    Это подтверждает, что FOR UPDATE действительно блокирует строку.
    """
    engine = create_async_engine(DATABASE_URL)
    user_id = uuid.uuid4()
    order_id = uuid.uuid4()

    async with AsyncSession(engine) as session:
        await session.execute(
            text("INSERT INTO users (id, email, name) VALUES (:id, :email, :name)"),
            {'id': str(user_id), 'email': f'null_{user_id}@test.com', 'name': 'Test User'}
        )
        await session.execute(
            text("INSERT INTO orders (id, user_id, status, total_amount) VALUES (:id, :user_id, 'created', 100.0)"),
            {'id': str(order_id), 'user_id': str(user_id)}
        )
        await session.commit()
    

    async def payment_attempt_1():
        async with AsyncSession(engine) as session1:
            await session1.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            await session1.execute(
                text("SELECT status FROM orders WHERE id = :order_id FOR UPDATE"),
                {'order_id': str(order_id)}
            )
            await asyncio.sleep(1)  # задержка
            await session1.execute(
                text("UPDATE orders SET status = 'paid' WHERE id = :order_id AND status = 'created'"),
                {'order_id': str(order_id)}
            )
            await session1.execute(
                text("INSERT INTO order_status_history (id, order_id, status, changed_at) VALUES (gen_random_uuid(), :order_id, 'paid', NOW())"),
                {'order_id': str(order_id)}
            )
            await session1.commit()
            return {'order_id': str(order_id), 'status': 'paid'}

    async def payment_attempt_2():
        await asyncio.sleep(0.1)
        async with AsyncSession(engine) as session2:
            service2 = PaymentService(session2)
            return await service2.pay_order_safe(order_id)

    start = time.time()
    results = await asyncio.gather(
        payment_attempt_1(),
        payment_attempt_2(),
        return_exceptions=True
    )
    delta = time.time() - start

    assert delta >= 1, f"итогое время {delta} сек"

    success_count = sum(1 for r in results if not isinstance(r, Exception))
    error_count = sum(1 for r in results if isinstance(r, Exception))
    assert success_count == 1
    assert error_count == 1

    print(f"итогое время {delta} сек")

    async with AsyncSession(engine) as session:
        await session.execute(text("DELETE FROM order_status_history WHERE order_id = :id"), {'id': str(order_id)})
        await session.execute(text("DELETE FROM orders WHERE id = :id"), {'id': str(order_id)})
        await session.execute(text("DELETE FROM users WHERE id = :id"), {'id': str(user_id)})
        await session.commit()

    await engine.dispose()
    # TODO: Реализовать тест с проверкой блокировки
    #raise NotImplementedError("TODO: Реализовать test_concurrent_payment_safe_with_explicit_timing")


@pytest.mark.asyncio
async def test_concurrent_payment_safe_multiple_orders():
    """
    Дополнительный тест: проверить, что блокировки не мешают разным заказам.
    
    TODO: Реализовать тест:
    1. Создать ДВА разных заказа
    2. Оплатить их ПАРАЛЛЕЛЬНО с помощью pay_order_safe()
    3. Проверить, что ОБА успешно оплачены
    
    Это показывает, что FOR UPDATE блокирует только конкретную строку,
    а не всю таблицу, что важно для производительности.
    """
    engine = create_async_engine(DATABASE_URL)

    user_id_1 = uuid.uuid4()
    user_id_2 = uuid.uuid4()
    order_id_1 = uuid.uuid4()
    order_id_2 = uuid.uuid4()

    async with AsyncSession(engine) as session:
        await session.execute(
            text("INSERT INTO users (id, email, name) VALUES (:id, :email, :name)"),
            {'id': str(user_id_1), 'email': f'null_{user_id_1}@test.com', 'name': 'User 1'}
        )
        await session.execute(
            text("INSERT INTO users (id, email, name) VALUES (:id, :email, :name)"),
            {'id': str(user_id_2), 'email': f'null_{user_id_2}@test.com', 'name': 'User 2'}
        )
        await session.execute(
            text("INSERT INTO orders (id, user_id, status, total_amount) VALUES (:id, :user_id, 'created', 100.0)"),
            {'id': str(order_id_1), 'user_id': str(user_id_1)}
        )
        await session.execute(
            text("INSERT INTO orders (id, user_id, status, total_amount) VALUES (:id, :user_id, 'created', 100.0)"),
            {'id': str(order_id_2), 'user_id': str(user_id_2)}
        )
        await session.commit()

    async def pay_order_1():
        async with AsyncSession(engine) as session1:
            return await PaymentService(session1).pay_order_safe(order_id_1)

    async def pay_order_2():
        async with AsyncSession(engine) as session2:
            return await PaymentService(session2).pay_order_safe(order_id_2)

    results = await asyncio.gather(
        pay_order_1(),
        pay_order_2(),
        return_exceptions=True
    )

    success_count = sum(1 for r in results if not isinstance(r, Exception))
    assert success_count == 2, f"кол-во успехов {success_count} != 2"

    async with AsyncSession(engine) as session:
        await session.execute(text("DELETE FROM order_status_history WHERE order_id = :id"), {'id': str(order_id_1)})
        await session.execute(text("DELETE FROM order_status_history WHERE order_id = :id"), {'id': str(order_id_2)})
        await session.execute(text("DELETE FROM orders WHERE id = :id"), {'id': str(order_id_1)})
        await session.execute(text("DELETE FROM orders WHERE id = :id"), {'id': str(order_id_2)})
        await session.execute(text("DELETE FROM users WHERE id = :id"), {'id': str(user_id_1)})
        await session.execute(text("DELETE FROM users WHERE id = :id"), {'id': str(user_id_2)})
        await session.commit()
    await engine.dispose()

    # TODO: Реализовать тест с несколькими заказами
    #raise NotImplementedError("TODO: Реализовать test_concurrent_payment_safe_multiple_orders")


if __name__ == "__main__":
    """
    Запуск теста:
    
    cd backend
    export PYTHONPATH=$(pwd)
    pytest app/tests/test_concurrent_payment_safe.py -v -s
    
    ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:
    ✅ test_concurrent_payment_safe_prevents_race_condition PASSED
    
    Вывод должен показывать:
    ✅ RACE CONDITION PREVENTED!
    Order XXX was paid only ONCE:
      - 2024-XX-XX: status = paid
    Second attempt was rejected: OrderAlreadyPaidError(...)
    """
    pytest.main([__file__, "-v", "-s"])