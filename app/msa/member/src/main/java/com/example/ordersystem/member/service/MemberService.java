package com.example.ordersystem.member.service;

import com.example.ordersystem.member.domain.Member;
import com.example.ordersystem.member.dto.LoginDto;
import com.example.ordersystem.member.dto.MemberSaveReqDto;
import com.example.ordersystem.member.repository.MemberRepository;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional
public class MemberService {
    private final MemberRepository memberRepository;
    private final PasswordEncoder passwordEncoder;

    public MemberService(MemberRepository memberRepository, PasswordEncoder passwordEncoder) {
        this.memberRepository = memberRepository;
        this.passwordEncoder = passwordEncoder;
    }

    @org.springframework.beans.factory.annotation.Value("${ADMIN_BOOTSTRAP_PASSWORD:}")
    private String adminBootstrapPassword;

    public Long save(MemberSaveReqDto memberSaveReqDto){
        if ("admin".equalsIgnoreCase(memberSaveReqDto.getLoginId())) {
            throw new IllegalArgumentException("관리자 전용 아이디입니다.");
        }
        if(memberRepository.findByLoginId(memberSaveReqDto.getLoginId()).isPresent()){
            throw new IllegalArgumentException("이미 존재하는 아이디입니다.");
        }

        if(memberRepository.findByEmail(memberSaveReqDto.getEmail()).isPresent()){
            throw new IllegalArgumentException("이미 존재하는 이메일입니다.");
        }

        String password = passwordEncoder.encode(memberSaveReqDto.getPassword());
        Member member = memberRepository.save(memberSaveReqDto.toEntity(password));
        return member.getId();
    }

    public Member findByLoginId(String loginId){
        return memberRepository.findByLoginId(loginId)
                .orElseThrow(() -> new IllegalArgumentException("존재하지 않는 회원입니다."));
    }

    public Member login(LoginDto dto){
        Member member = memberRepository.findByLoginId(dto.getLoginId())
                .orElseThrow(() -> new IllegalArgumentException("아이디 또는 비밀번호가 일치하지 않습니다."));

        requireAdminConfigured(member);
        if(!passwordEncoder.matches(dto.getPassword(), member.getPassword())){
            throw new IllegalArgumentException("아이디 또는 비밀번호가 일치하지 않습니다.");
        }

        return member;
    }

    // 로그인과 토큰 갱신에 같은 관리자 초기화 조건을 적용한다.
    public void requireAdminConfigured(Member member) {
        if (member.getRole() == com.example.ordersystem.member.domain.Role.ADMIN
                && (adminBootstrapPassword == null || adminBootstrapPassword.isBlank())) {
            throw new IllegalArgumentException("관리자 비밀번호 설정이 필요합니다.");
        }
    }
}
