package com.example.ordersystem.product.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@AllArgsConstructor
@NoArgsConstructor
@Data
@Builder
public class ProductResDto {
    private Long id;
    private String name;
    private String category;
    private String description;
    private String imageUrl;
    private int price;
    private int stockQuantity;
}
