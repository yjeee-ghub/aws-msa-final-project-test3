package com.example.ordersystem.ordering.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class OrderCreateDto {
    // 잘못된 수량으로 재고가 증가하지 않도록 서버에서도 검사한다.
    @jakarta.validation.constraints.NotNull
    @jakarta.validation.constraints.Positive
    private Long productId;
    @jakarta.validation.constraints.NotNull
    @jakarta.validation.constraints.Min(1)
    @jakarta.validation.constraints.Max(999)
    private Integer productCount;
}
