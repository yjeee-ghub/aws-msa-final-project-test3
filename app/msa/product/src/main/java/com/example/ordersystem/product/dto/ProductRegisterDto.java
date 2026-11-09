package com.example.ordersystem.product.dto;

import com.example.ordersystem.product.domain.Product;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.web.multipart.MultipartFile;

@NoArgsConstructor
@AllArgsConstructor
@Data
public class ProductRegisterDto {
    private String name;
    private String category;
    private String description;
    private String imageUrl;
    private MultipartFile imageFile;
    private int price;
    private int stockQuantity;

    public Product toEntity(Long userId, String finalImageUrl){
        return Product.builder()
                .name(this.name)
                .category(this.category)
                .description(this.description)
                .imageUrl(finalImageUrl)
                .price(this.price)
                .stockQuantity(this.stockQuantity)
                .memberId(userId)
                .build();
    }
}
