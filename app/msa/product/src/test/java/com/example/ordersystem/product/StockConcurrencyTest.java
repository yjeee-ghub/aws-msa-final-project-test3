package com.example.ordersystem.product;

import com.example.ordersystem.product.domain.Product;
import com.example.ordersystem.product.dto.ProductUpdateStockDto;
import com.example.ordersystem.product.repository.ProductRepository;
import com.example.ordersystem.product.service.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.*;
import java.util.concurrent.*;
import static org.junit.jupiter.api.Assertions.*;

@DataJpaTest(showSql = false)
@ActiveProfiles("test")
@Import(ProductService.class)
@Transactional(propagation = Propagation.NOT_SUPPORTED)
class StockConcurrencyTest {
    @Autowired ProductRepository repository;
    @Autowired ProductService service;
    @MockBean S3Service s3;

    @Test void simultaneousOrdersCannotSellSameStockTwice() throws Exception {
        var product = repository.saveAndFlush(Product.builder().name("stock-test").price(1000)
                .stockQuantity(2).memberId(1L).build());
        var start = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(2);
        Callable<Boolean> order = () -> {
            start.await();
            try {
                var dto = new ProductUpdateStockDto();
                dto.setProductId(product.getId()); dto.setProductQuantity(2);
                service.updateStockQuantity(dto);
                return true;
            } catch (IllegalArgumentException expected) { return false; }
        };
        try {
            var first = pool.submit(order); var second = pool.submit(order);
            start.countDown();
            int successes = (first.get(15, TimeUnit.SECONDS) ? 1 : 0) + (second.get(15, TimeUnit.SECONDS) ? 1 : 0);
            assertEquals(1, successes);
            assertEquals(0, repository.findById(product.getId()).orElseThrow().getStockQuantity());
        } finally { pool.shutdownNow(); }
    }
}
