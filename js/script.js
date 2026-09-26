/* =========================================================
   スキー場絶景集  script.js（jQuery）
   1. 日本地図のスポット（トップページ）
   2. 「日本地図へ」のスクロール・地図や写真がふわっと出てくる動き
   3. 右側のタブ（トップページ）
   4. 写真の拡大表示＝ライトボックス（スキー場ページ）
   5. 「日本地図にもどる」ボタン（スキー場ページ）
========================================================= */

if (window.jQuery) {
    $(function () {
        setupMapSpots();
        setupScrollCue();
        setupReveal();
        setupSideTab();
        setupGallery();
        setupBackLink();
    });
} else {
    // jQuery が読み込めなかったとき（ネットにつながっていないときなど）は、
    // CSS で隠している地図や写真をそのまま表示する
    document.documentElement.className += ' no-jquery';
}


/* ---------------------------------------------------------
   1. 日本地図のスポット
   ・HTML の data-lat（緯度）/ data-lon（経度）から、地図のどこに点を置くか計算する
   ・パソコン：カーソルを乗せるだけで青 → 赤になり、スキー場名が出る（見た目は CSS の .is-active）
   ・スマホ：1回目のタップで名前を出し、2回目で開く
   ・開くページは HTML の target="_blank" で別のタブになる
--------------------------------------------------------- */

// 地図画像（日本地図 緑.png）がどんな図法で描かれているかを計算で割り出した値。
// 基本的に触らなくてOK。スキー場を増やすときは HTML に緯度・経度を書くだけ。
var MAP_PROJECTION = {
    width: 741,    // 元の地図画像の幅（px）
    height: 582,   // 元の地図画像の高さ（px）
    n: 0.586,      // 円錐図法の係数
    lon0: 137,     // 基準の経度
    a: 2847.1848, b: 396.5492, c: 792.2543,     // 横位置の係数
    d: 397.5101, e: -2826.0499, f: -2870.9656   // 縦位置の係数
};

// 緯度・経度 → 地図画像の左上からの位置（％）
function latLonToPercent(lat, lon) {
    var p = MAP_PROJECTION;
    var rad = Math.PI / 180;
    var rho = Math.pow(Math.tan(Math.PI / 4 - lat * rad / 2), p.n) / p.n;
    var theta = p.n * (lon - p.lon0) * rad;
    var x = rho * Math.sin(theta);
    var y = -rho * Math.cos(theta);

    return {
        left: (p.a * x + p.b * y + p.c) / p.width * 100,
        top: (p.d * x + p.e * y + p.f) / p.height * 100
    };
}

function setupMapSpots() {
    var $spots = $('#js-map .spot');
    if (!$spots.length) return;

    // 緯度・経度から点の位置を決める
    $spots.each(function () {
        var pos = latLonToPercent($(this).data('lat'), $(this).data('lon'));
        $(this).css({ left: pos.left + '%', top: pos.top + '%' });
    });

    // パソコン（マウス）：カーソルを乗せただけで赤＋名前、外したら元に戻す
    // （pointerType で「マウスか指か」を見分けるので、タッチ対応のノートPCでもマウスならこちらになる）
    $spots.on('pointerenter', function (e) {
        if (e.originalEvent.pointerType === 'mouse') {
            $(this).addClass('is-active');
        }
    }).on('pointerleave', function (e) {
        if (e.originalEvent.pointerType === 'mouse') {
            $(this).removeClass('is-active');
        }
    });

    // スマホ（指でタップ）：1回目のタップは名前を出すだけ、もう一度タップで開く
    var inputType = 'mouse';
    $spots.on('pointerdown', function (e) {
        inputType = e.originalEvent.pointerType;
    }).on('click', function (e) {
        if (inputType !== 'mouse' && !$(this).hasClass('is-active')) {
            e.preventDefault();
            $spots.removeClass('is-active');
            $(this).addClass('is-active');
        }
    });

    // スマホで点以外の場所をタップしたら名前を消す
    $(document).on('pointerdown', function (e) {
        if (e.originalEvent.pointerType !== 'mouse' && !$(e.target).closest('.spot').length) {
            $spots.removeClass('is-active');
        }
    });
}


/* ---------------------------------------------------------
   2. 「日本地図へ」を押したら地図までなめらかにスクロール
      スクロールして見えてきたものを、下からふわっと出す
      （class="reveal" が付いているもの＋スキー場ページの写真1枚1枚）
--------------------------------------------------------- */
function setupScrollCue() {
    $('#js-scroll-cue').on('click', function (e) {
        e.preventDefault();
        var target = $($(this).attr('href')).offset().top;
        $('html, body').animate({ scrollTop: target }, 700);
    });
}

function setupReveal() {
    // 最初は CSS で隠れているもの（地図と、スキー場ページの写真1枚1枚）
    var $targets = $('.reveal, #js-gallery li');
    if (!$targets.length) return;

    function check() {
        // 画面の下から15%くらいのところまで来たら表示する
        var scrollTop = $(window).scrollTop();
        var winHeight = $(window).height();
        var line = scrollTop + winHeight * 0.85;
        // ページのいちばん下まで来たら、残りも全部出す（最後の写真が出ないままにならないように）
        if (scrollTop + winHeight >= $(document).height() - 5) {
            line = Infinity;
        }
        var count = 0;  // 同時に出るものは少しずつ時間差をつける
        $targets.not('.is-visible').each(function () {
            if ($(this).offset().top < line) {
                $(this).css('transition-delay', Math.min(count, 6) * 0.08 + 's').addClass('is-visible');
                count++;
            }
        });
    }

    $(window).on('scroll resize', check);
    check();
}


/* ---------------------------------------------------------
   3. 右側のタブ
   ・リンク先がまだ無い（href="#"）間は「準備中」のお知らせを出す
   ・サイトができたら index.html の href を書きかえるだけで普通のリンクになる
--------------------------------------------------------- */
function setupSideTab() {
    var $toast = $('#js-toast');

    $('#js-side-tab').on('click', function (e) {
        if ($(this).attr('href') === '#') {
            e.preventDefault();
            $toast.html('スキー場以外の絶景集は準備中です。<br>お楽しみに！')
                .stop(true, true)
                .fadeIn(200)
                .delay(2200)
                .fadeOut(400);
        }
    });
}


/* ---------------------------------------------------------
   4. 写真の拡大表示（ライトボックス）
   ・写真をクリック → 大きく表示
   ・‹ › ボタン／キーボードの ← → ／スマホは左右スワイプで前後の写真へ
   ・× ボタン／暗いところをクリック／Esc キーで閉じる
--------------------------------------------------------- */
function setupGallery() {
    var $links = $('#js-gallery .gallery-link');
    if (!$links.length) return;

    var $lightbox = $('#js-lightbox');
    var $image = $lightbox.find('.lightbox-image');
    var $count = $lightbox.find('.lightbox-count');
    var current = 0;      // いま表示している写真の番号（0から数える）
    var $lastFocus = $(); // 閉じたときにフォーカスを戻す場所

    // 見出しに写真の枚数を表示（写真を増やすと自動で変わる）
    $('#js-photo-count').text('全' + $links.length + '枚');

    // 大きい写真の読み込みが終わったら、ふわっと表示
    $image.on('load', function () {
        $(this).stop(true).animate({ opacity: 1 }, 250);
    });

    function show(index) {
        current = (index + $links.length) % $links.length; // 最後の次は最初に戻る
        var $link = $links.eq(current);
        var src = $link.attr('href');

        $count.text((current + 1) + ' / ' + $links.length);

        if ($image.attr('src') === src) {
            $image.stop(true).css('opacity', 1);
            return;
        }
        $image.stop(true).css('opacity', 0).attr({
            src: src,
            alt: $link.find('img').attr('alt')
        });

        // 前後の写真を先に読み込んでおく（切りかえが速くなる）
        $.each([current - 1, current + 1], function (i, n) {
            new Image().src = $links.eq((n + $links.length) % $links.length).attr('href');
        });
    }

    function open(index) {
        $lastFocus = $(document.activeElement);
        show(index);
        $lightbox.addClass('is-open');
        $('body').addClass('is-locked');
        $lightbox.find('.lightbox-close').trigger('focus');
    }

    function close() {
        $lightbox.removeClass('is-open');
        $('body').removeClass('is-locked');
        $lastFocus.trigger('focus');
    }

    $links.on('click', function (e) {
        e.preventDefault();
        open($links.index(this));
    });

    $lightbox.find('.lightbox-prev').on('click', function () {
        show(current - 1);
    });
    $lightbox.find('.lightbox-next').on('click', function () {
        show(current + 1);
    });
    $lightbox.find('.lightbox-close').on('click', close);

    // 写真の外側（暗いところ）をクリックしたら閉じる
    $lightbox.on('click', function (e) {
        if (e.target === this) close();
    });

    // キーボード：← → で切りかえ、Esc で閉じる
    $(document).on('keydown', function (e) {
        if (!$lightbox.hasClass('is-open')) return;
        if (e.key === 'ArrowLeft') show(current - 1);
        if (e.key === 'ArrowRight') show(current + 1);
        if (e.key === 'Escape') close();
    });

    // スマホ：左右にスワイプで切りかえ
    var touchStartX = null;
    $lightbox.on('touchstart', function (e) {
        touchStartX = e.originalEvent.touches[0].clientX;
    }).on('touchend', function (e) {
        if (touchStartX === null) return;
        var diff = e.originalEvent.changedTouches[0].clientX - touchStartX;
        if (Math.abs(diff) > 50) {
            show(diff < 0 ? current + 1 : current - 1);
        }
        touchStartX = null;
    });
}


/* ---------------------------------------------------------
   5. 「日本地図にもどる」ボタン
   ・地図から別のタブで開いたときは、このタブを閉じて元の地図のタブに戻る
   ・このページを直接開いたとき（元の地図のタブがないとき）は、ふつうに地図のページへ移動する
--------------------------------------------------------- */
function setupBackLink() {
    $('.back-link').on('click', function (e) {
        var mapTab = window.opener;  // このタブを開いた元のタブ（地図のページ）
        if (!mapTab || mapTab.closed) return;  // 元のタブがない → ふつうのリンクとして地図へ

        e.preventDefault();
        var href = $(this).attr('href');
        mapTab.focus();
        window.close();

        // ブラウザの都合でタブを閉じられなかったときは、ふつうに地図のページへ移動
        setTimeout(function () {
            location.href = href;
        }, 300);
    });
}
