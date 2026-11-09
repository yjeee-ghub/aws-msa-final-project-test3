package com.example.ordersystem.member.service;

import com.example.ordersystem.member.domain.*;
import com.example.ordersystem.member.repository.MemberRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
public class InitialDataLoader implements CommandLineRunner {
    private final MemberRepository repository;
    private final PasswordEncoder encoder;
    private final String password;
    private final String email;

    public InitialDataLoader(MemberRepository repository, PasswordEncoder encoder,
            @Value("${ADMIN_BOOTSTRAP_PASSWORD:}") String password,
            @Value("${ADMIN_BOOTSTRAP_EMAIL:}") String email) {
        this.repository = repository; this.encoder = encoder;
        this.password = password; this.email = email.trim();
    }

    @Override @Transactional
    public void run(String... args) {
        // 공개된 기본 비밀번호 대신 Kubernetes Secret의 값으로 생성/갱신한다.
        if (password.isBlank()) return;
        if (password.length() < 12 || password.length() > 64) {
            throw new IllegalArgumentException("관리자 비밀번호는 12~64자로 설정하세요.");
        }
        if (!email.matches("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$")) {
            throw new IllegalArgumentException("유효한 관리자 이메일을 설정하세요.");
        }
        Member emailOwner = repository.findByEmail(email).orElse(null);
        if (emailOwner != null && !"admin".equals(emailOwner.getLoginId())) {
            throw new IllegalStateException("관리자 이메일이 다른 회원에게 사용 중입니다. 다른 주소를 설정하세요.");
        }
        Member existing = repository.findByLoginId("admin").orElse(null);
        if (existing != null) {
            if (existing.getRole() != Role.ADMIN) {
                throw new IllegalStateException("admin 아이디가 일반 회원에게 사용 중입니다.");
            }
            if (!encoder.matches(password, existing.getPassword())) {
                existing.changePassword(encoder.encode(password));
            }
            existing.changeEmail(email);
            return;
        }
        repository.save(Member.builder().loginId("admin").name("관리자").nickname("관리자")
                .email(email).password(encoder.encode(password)).role(Role.ADMIN).build());
    }
}
