package com.example.ordersystem.product.controller;

import com.example.ordersystem.product.domain.Product;
import com.example.ordersystem.product.dto.ProductRegisterDto;
import com.example.ordersystem.product.dto.ProductResDto;
import com.example.ordersystem.product.dto.ProductUpdateStockDto;
import com.example.ordersystem.product.service.ProductService;
import java.io.IOException;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/product")
public class ProductController {
  private final ProductService productService;

  @org.springframework.beans.factory.annotation.Value("${INTERNAL_SERVICE_TOKEN:}")
  private String internalToken;

  private void internal(String supplied) {
    if (internalToken == null
        || internalToken.length() < 32
        || supplied == null
        || !java.security.MessageDigest.isEqual(
            internalToken.getBytes(java.nio.charset.StandardCharsets.UTF_8),
            supplied.getBytes(java.nio.charset.StandardCharsets.UTF_8)))
      throw new org.springframework.web.server.ResponseStatusException(HttpStatus.FORBIDDEN);
  }

  public ProductController(ProductService productService) {
    this.productService = productService;
  }

  @PostMapping(
      value = "/create",
      consumes = {MediaType.MULTIPART_FORM_DATA_VALUE})
  public ResponseEntity<?> productCreate(
      @ModelAttribute ProductRegisterDto dto,
      @RequestHeader("X-User-Id") String userId,
      @RequestHeader("X-User-Role") String role)
      throws IOException {
    if (!"ROLE_ADMIN".equals(role)) {
      throw new org.springframework.web.server.ResponseStatusException(HttpStatus.FORBIDDEN);
    }
    Product product = productService.productCreate(dto, userId);
    return new ResponseEntity<>(product.getId(), HttpStatus.CREATED);
  }

  @GetMapping("/list")
  public ResponseEntity<?> productList() {
    List<ProductResDto> productList = productService.productList();
    return new ResponseEntity<>(productList, HttpStatus.OK);
  }

  @GetMapping("/{id}")
  public ResponseEntity<?> productDetail(@PathVariable Long id) {
    ProductResDto productResDto = productService.productDetail(id);
    return new ResponseEntity<>(productResDto, HttpStatus.OK);
  }

  @PutMapping("/updatestock")
  public ResponseEntity<?> updateStock(
      @RequestBody ProductUpdateStockDto productUpdateStockDto,
      @RequestHeader(value = "X-Internal-Token", required = false) String token) {
    internal(token);
    Product product = productService.updateStockQuantity(productUpdateStockDto);
    return new ResponseEntity<>(product.getId(), HttpStatus.OK);
  }

  @PostMapping("/{id}/purchase")
  public ResponseEntity<?> purchaseProduct(
      @PathVariable Long id,
      @RequestHeader(value = "X-Internal-Token", required = false) String token) {
    internal(token);
    Product product = productService.purchaseProduct(id);
    return new ResponseEntity<>(product.getId(), HttpStatus.OK);
  }
}
