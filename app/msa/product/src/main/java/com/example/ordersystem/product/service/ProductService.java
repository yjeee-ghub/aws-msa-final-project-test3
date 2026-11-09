package com.example.ordersystem.product.service;

import com.example.ordersystem.product.domain.Product;
import com.example.ordersystem.product.dto.ProductEditDto;
import com.example.ordersystem.product.dto.ProductRegisterDto;
import com.example.ordersystem.product.dto.ProductResDto;
import com.example.ordersystem.product.dto.ProductUpdateStockDto;
import com.example.ordersystem.product.repository.ProductRepository;
import jakarta.persistence.EntityNotFoundException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.util.List;

@Service
@Transactional
public class ProductService {
    private final ProductRepository productRepository;
    private final S3Service s3Service;

    public ProductService(ProductRepository productRepository, S3Service s3Service) {
        this.productRepository = productRepository;
        this.s3Service = s3Service;
    }

    public Product productCreate(ProductRegisterDto dto, String userId) throws IOException {
        String finalImageUrl = dto.getImageUrl();
        if (dto.getImageFile() != null && !dto.getImageFile().isEmpty()) {
            finalImageUrl = s3Service.uploadFile(dto.getImageFile());
        }

        Long memberId = 1L;
        if (userId != null && !userId.isBlank()) {
            memberId = Long.parseLong(userId);
        }

        return productRepository.save(dto.toEntity(memberId, finalImageUrl));
    }

    @Transactional(readOnly = true)
    public ProductResDto productDetail(Long id){
        Product product = productRepository.findByIdAndDeletedAtIsNull(id)
                .orElseThrow(() -> new EntityNotFoundException("없는 상품입니다."));
        return toDto(product);
    }

    @Transactional(readOnly = true)
    public List<ProductResDto> productList(){
        return productRepository.findAllByDeletedAtIsNullOrderByIdDesc()
                .stream()
                .map(this::toDto)
                .toList();
    }

    public ProductResDto productEdit(Long id, ProductEditDto dto) throws IOException {
        Product product = activeProductForUpdate(id);
        if (dto.getStockQuantity() != null) requireExpectedStock(product, dto.getExpectedStockQuantity());
        String imageUrl = product.getImageUrl();
        if (dto.getImageFile() != null && !dto.getImageFile().isEmpty()) {
            imageUrl = s3Service.uploadFile(dto.getImageFile());
        }
        product.edit(dto.getName().trim(), dto.getCategory(), dto.getDescription(),
                dto.getPrice(), dto.getStockQuantity(), imageUrl);
        return toDto(product);
    }

    public ProductResDto setAvailableStock(Long id, int expected, int quantity) {
        Product product = activeProductForUpdate(id);
        requireExpectedStock(product, expected);
        product.setAvailableStock(quantity);
        return toDto(product);
    }

    private void requireExpectedStock(Product product, Integer expected) {
        if (!product.getStockQuantity().equals(expected)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "재고가 변경됐습니다. 상품을 다시 불러와 주세요.");
        }
    }

    public void productDelete(Long id) {
        // Keep the row for existing order reservations and stock compensation.
        Product product = productRepository.findForStockUpdate(id)
                .orElseThrow(() -> new EntityNotFoundException("없는 상품입니다."));
        product.removeFromCatalog();
    }

    public Product updateStockQuantity(ProductUpdateStockDto productUpdateStockDto){
        Product product = activeProductForUpdate(productUpdateStockDto.getProductId());
        if (productUpdateStockDto.getProductQuantity() == null) {
            throw new IllegalArgumentException("구매 수량이 없습니다.");
        }
        product.updateStockQuantity(productUpdateStockDto.getProductQuantity());
        return product;
    }

    public Product purchaseProduct(Long id){
        Product product = activeProductForUpdate(id);
        product.updateStockQuantity(1);
        return product;
    }

    private Product activeProductForUpdate(Long id) {
        return productRepository.findForStockUpdate(id)
                .filter(Product::isActive)
                .orElseThrow(() -> new EntityNotFoundException("없는 상품입니다."));
    }

    private ProductResDto toDto(Product product){
        return ProductResDto.builder()
                .id(product.getId())
                .name(product.getName())
                .category(product.getCategory())
                .description(product.getDescription())
                .imageUrl(product.getImageUrl())
                .price(product.getPrice())
                .stockQuantity(product.getStockQuantity())
                .build();
    }
}
