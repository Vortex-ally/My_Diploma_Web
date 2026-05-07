// Profile menu functionality
document.addEventListener('DOMContentLoaded', function() {
    try {
        const avatar = document.querySelector('.avatar');
        const avatarImg = document.querySelector('.avatar img');
        const subtitle = document.querySelector('.top-bar-left .subtitle');
        const sidebarLinks = document.querySelectorAll('.sidebar .nav-links a');
        
        console.log('Header.js loaded, sidebar links:', sidebarLinks.length);
        
        if (!avatar || !avatarImg || !subtitle) {
            console.log('Header.js: missing elements, skipping profile menu');
            return;
        }
        
        const profileMenu = document.createElement('div');
        
        // Create profile menu
        profileMenu.className = 'profile-menu';
        profileMenu.innerHTML = 
            '<div class="profile-menu-header">' +
                '<div class="profile-menu-avatar">' +
                    '<img src="https://ui-avatars.com/api/?name=' + avatarImg.alt + '&background=4f46e5&color=fff" alt="Profile">' +
                '</div>' +
                '<div class="profile-menu-info">' +
                    '<h4>' + avatarImg.alt + '</h4>' +
                    '<p>' + subtitle.textContent.trim() + '</p>' +
                '</div>' +
            '</div>' +
            '<div class="profile-menu-items">' +
                '<a href="#profile" class="profile-menu-item">' +
                    '<i class="fas fa-user"></i>' +
                    '<span>Профіль</span>' +
                '</a>' +
                '<a href="#settings" class="profile-menu-item">' +
                    '<i class="fas fa-cog"></i>' +
                    '<span>Налаштування</span>' +
                '</a>' +
                '<a href="#avatar" class="profile-menu-item">' +
                    '<i class="fas fa-image"></i>' +
                    '<span>Змінити аватарку</span>' +
                '</a>' +
                '<div class="profile-menu-divider"></div>' +
                '<a href="/logout/" class="profile-menu-item logout">' +
                    '<i class="fas fa-sign-out-alt"></i>' +
                    '<span>Вийти</span>' +
                '</a>' +
            '</div>';
        
        // Add menu to body
        document.body.appendChild(profileMenu);
        
        // Toggle menu on avatar click
        avatar.addEventListener('click', function(e) {
            e.stopPropagation();
            profileMenu.classList.toggle('active');
        });
        
        // Close menu when clicking outside
        document.addEventListener('click', function(e) {
            if (!profileMenu.contains(e.target)) {
                profileMenu.classList.remove('active');
            }
        });
        
        // Handle menu item clicks
        profileMenu.querySelectorAll('.profile-menu-item').forEach(function(item) {
            item.addEventListener('click', function(e) {
                e.preventDefault();
                var href = this.getAttribute('href');
                
                if (href === '#profile') {
                    alert('Профіль - в розробці');
                } else if (href === '#settings') {
                    alert('Налаштування - в розробці');
                } else if (href === '#avatar') {
                    alert('Зміна аватарки - в розробці');
                } else if (href === '/logout/') {
                    window.location.href = href;
                }
                
                profileMenu.classList.remove('active');
            });
        });
        
        console.log('Header.js initialized successfully');
    } catch (e) {
        console.error('Header.js error:', e);
    }
});
