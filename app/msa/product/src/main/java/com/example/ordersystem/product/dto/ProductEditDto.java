package com.example.ordersystem.product.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import lombok.Data;
import org.springframework.web.multipart.MultipartFile;

@Data
public class ProductEditDto {
    @NotBlank
    @Size(max = 255)
    private String name;

    @Size(max = 255)
    private String category;

    @Size(max = 1000)
    private String description;

    @NotNull
    @PositiveOrZero
    private Integer price;

    @PositiveOrZero
    private Integer stockQuantity;

    @PositiveOrZero
    private Integer expectedStockQuantity;

    private MultipartFile imageFile;
}
