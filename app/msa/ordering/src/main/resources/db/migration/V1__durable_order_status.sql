-- 기존 주문 데이터는 유지하고, 신규 설치와 기존 ENUM 모두 같은 상태 표현을 사용합니다.
CREATE TABLE IF NOT EXISTS ordering (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    member_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    quantity INT NOT NULL,
    order_status VARCHAR(32),
    created_time DATETIME(6),
    updated_time DATETIME(6)
);
ALTER TABLE ordering MODIFY COLUMN order_status VARCHAR(32);
