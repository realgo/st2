# Licensed to the StackStorm, Inc ('StackStorm') under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from st2tests.base import CleanDbTestCase
from st2common.persistence.auth import User
from st2common.persistence.rbac import Role
from st2common.persistence.rbac import PermissionGrant
from st2common.persistence.rbac import GroupToRoleMapping
from st2common.models.db.auth import UserDB
from st2common.models.api.rbac import RoleDefinitionFileFormatAPI
from st2common.models.api.rbac import UserRoleAssignmentFileFormatAPI
from st2common.services.rbac import get_roles_for_user
from st2common.services.rbac import create_role
from st2common.services.rbac import assign_role_to_user
from st2common.services.rbac import create_group_to_role_map
from st2common.rbac.syncer import RBACDefinitionsDBSyncer
from st2common.rbac.syncer import RBACRemoteGroupToRoleSyncer

__all__ = [
    'RBACDefinitionsDBSyncerTestCase',
    'RBACRemoteGroupToRoleSyncerTestCase'
]


class BaseRBACDefinitionsDBSyncerTestCase(CleanDbTestCase):
    def setUp(self):
        super(BaseRBACDefinitionsDBSyncerTestCase, self).setUp()

        self.roles = {}
        self.users = {}

        self._insert_mock_data()

    def _insert_mock_data(self):
        # Insert some mock users
        user_1_db = UserDB(name='user_1')
        user_1_db = User.add_or_update(user_1_db)
        self.users['user_1'] = user_1_db

        user_2_db = UserDB(name='user_2')
        user_2_db = User.add_or_update(user_2_db)
        self.users['user_2'] = user_2_db


class RBACDefinitionsDBSyncerTestCase(BaseRBACDefinitionsDBSyncerTestCase):
    def test_sync_roles_no_definitions(self):
        syncer = RBACDefinitionsDBSyncer()

        # No definitions
        created_role_dbs, deleted_role_dbs = syncer.sync_roles(role_definition_apis=[])
        self.assertItemsEqual(created_role_dbs, [])
        self.assertItemsEqual(deleted_role_dbs, [])

    def test_sync_roles_single_role_definition_no_grants(self):
        syncer = RBACDefinitionsDBSyncer()

        # One role with no grants
        api = RoleDefinitionFileFormatAPI(name='test_role_1', description='test description 1',
                                          permission_grants=[])
        created_role_dbs, deleted_role_dbs = syncer.sync_roles(role_definition_apis=[api])
        self.assertEqual(len(created_role_dbs), 1)
        self.assertItemsEqual(deleted_role_dbs, [])
        self.assertEqual(created_role_dbs[0].name, 'test_role_1')
        self.assertEqual(created_role_dbs[0].description, 'test description 1')
        self.assertItemsEqual(created_role_dbs[0].permission_grants, [])

        # Assert role has been created in the DB
        self.assertRoleDBObjectExists(role_db=created_role_dbs[0])

    def test_sync_roles_single_role_definition_three_grants(self):
        syncer = RBACDefinitionsDBSyncer()

        # One role with two grants
        permission_grants = [
            {
                'resource_uid': 'pack:mapack1',
                'permission_types': ['pack_all']
            },
            {
                'resource_uid': 'pack:mapack2',
                'permission_types': ['rule_view', 'action_view']
            },
            {
                'permission_types': ['sensor_list', 'action_list']
            }
        ]
        api = RoleDefinitionFileFormatAPI(name='test_role_2', description='test description 2',
                                          permission_grants=permission_grants)
        created_role_dbs, deleted_role_dbs = syncer.sync_roles(role_definition_apis=[api])
        self.assertEqual(len(created_role_dbs), 1)
        self.assertItemsEqual(deleted_role_dbs, [])
        self.assertEqual(created_role_dbs[0].name, 'test_role_2')
        self.assertEqual(created_role_dbs[0].description, 'test description 2')
        self.assertEqual(len(created_role_dbs[0].permission_grants), 3)

        # Assert role and grants have been created in the DB
        self.assertRoleDBObjectExists(role_db=created_role_dbs[0])

        for permission_grant_id in created_role_dbs[0].permission_grants:
            self.assertGrantDBObjectExists(permission_grant_id)

        grant_db = PermissionGrant.get_by_id(str(created_role_dbs[0].permission_grants[0]))
        self.assertEqual(grant_db.resource_uid, permission_grants[0]['resource_uid'])
        self.assertEqual(grant_db.resource_type, 'pack')
        self.assertEqual(grant_db.permission_types, permission_grants[0]['permission_types'])

        grant_db = PermissionGrant.get_by_id(str(created_role_dbs[0].permission_grants[2]))
        self.assertEqual(grant_db.resource_uid, None)
        self.assertEqual(grant_db.resource_type, None)
        self.assertEqual(grant_db.permission_types, permission_grants[2]['permission_types'])

    def test_sync_roles_locally_removed_roles_are_removed_from_db(self):
        syncer = RBACDefinitionsDBSyncer()

        # Initial state, DB is empty, we sync with two roles defined on disk
        self.assertEqual(len(Role.get_all()), 0)

        api1 = RoleDefinitionFileFormatAPI(name='test_role_1', description='test description 1',
                                           permission_grants=[])
        api2 = RoleDefinitionFileFormatAPI(name='test_role_2', description='test description 2',
                                           permission_grants=[])
        created_role_dbs, deleted_role_dbs = syncer.sync_roles(role_definition_apis=[api1, api2])
        self.assertEqual(len(created_role_dbs), 2)
        self.assertItemsEqual(deleted_role_dbs, [])

        # Assert role and grants have been created in the DB
        self.assertEqual(len(Role.get_all()), 2)
        self.assertRoleDBObjectExists(role_db=created_role_dbs[0])
        self.assertRoleDBObjectExists(role_db=created_role_dbs[1])

        # We sync again, this time with one role (role 1) removed locally
        created_role_dbs, deleted_role_dbs = syncer.sync_roles(role_definition_apis=[api2])
        self.assertEqual(len(created_role_dbs), 1)
        self.assertEqual(len(deleted_role_dbs), 2)

        # Assert role and grants have been created in the DB
        self.assertEqual(len(Role.get_all()), 1)
        self.assertRoleDBObjectExists(role_db=created_role_dbs[0])
        self.assertEqual(Role.get_all()[0].name, 'test_role_2')

    def test_sync_user_assignments_single_role_assignment(self):
        syncer = RBACDefinitionsDBSyncer()

        self._insert_mock_roles()

        # Initial state, no roles
        role_dbs = get_roles_for_user(user_db=self.users['user_1'])
        self.assertItemsEqual(role_dbs, [])

        # Do the sync with a single role defined
        api = UserRoleAssignmentFileFormatAPI(username='user_1',
                                              roles=['role_1'])
        syncer.sync_users_role_assignments(role_assignment_apis=[api])

        role_dbs = get_roles_for_user(user_db=self.users['user_1'])
        self.assertItemsEqual(role_dbs, [self.roles['role_1']])

    def test_sync_user_assignments_multiple_custom_roles_assignments(self):
        syncer = RBACDefinitionsDBSyncer()

        self._insert_mock_roles()

        # Initial state, no roles
        role_dbs = get_roles_for_user(user_db=self.users['user_2'])
        self.assertItemsEqual(role_dbs, [])

        # Do the sync with two roles defined
        api = UserRoleAssignmentFileFormatAPI(username='user_2',
                                              roles=['role_1', 'role_2'])
        syncer.sync_users_role_assignments(role_assignment_apis=[api])

        role_dbs = get_roles_for_user(user_db=self.users['user_2'])
        self.assertEqual(len(role_dbs), 2)
        self.assertEqual(role_dbs[0], self.roles['role_1'])
        self.assertEqual(role_dbs[1], self.roles['role_2'])

    def test_sync_user_assignments_locally_removed_assignments_are_removed_from_db(self):
        syncer = RBACDefinitionsDBSyncer()

        self._insert_mock_roles()

        # Initial state, no roles
        role_dbs = get_roles_for_user(user_db=self.users['user_2'])
        self.assertItemsEqual(role_dbs, [])

        # Do the sync with two roles defined
        api = UserRoleAssignmentFileFormatAPI(username='user_2',
                                              roles=['role_1', 'role_2'])
        syncer.sync_users_role_assignments(role_assignment_apis=[api])

        role_dbs = get_roles_for_user(user_db=self.users['user_2'])
        self.assertEqual(len(role_dbs), 2)
        self.assertEqual(role_dbs[0], self.roles['role_1'])
        self.assertEqual(role_dbs[1], self.roles['role_2'])

        # Do the sync with one role defined (one should be removed from the db)
        api = UserRoleAssignmentFileFormatAPI(username='user_2',
                                              roles=['role_2'])
        syncer.sync_users_role_assignments(role_assignment_apis=[api])

        role_dbs = get_roles_for_user(user_db=self.users['user_2'])
        self.assertEqual(len(role_dbs), 1)
        self.assertEqual(role_dbs[0], self.roles['role_2'])

    def test_sync_assignments_user_doesnt_exist_in_db(self):
        # Make sure that the assignments for the users which don't exist in the db are still saved
        syncer = RBACDefinitionsDBSyncer()

        self._insert_mock_roles()

        # Initial state, no roles
        user_db = UserDB(name='doesntexistwhaha')
        role_dbs = get_roles_for_user(user_db=user_db)
        self.assertItemsEqual(role_dbs, [])

        # Do the sync with two roles defined
        api = UserRoleAssignmentFileFormatAPI(username=user_db.name,
                                              roles=['role_1', 'role_2'])
        syncer.sync_users_role_assignments(role_assignment_apis=[api])

        role_dbs = get_roles_for_user(user_db=user_db)
        self.assertEqual(len(role_dbs), 2)
        self.assertEqual(role_dbs[0], self.roles['role_1'])
        self.assertEqual(role_dbs[1], self.roles['role_2'])

    def test_sync_remote_assignments_are_not_manipulated(self):
        # Verify remote assignments are not manipulated.
        syncer = RBACDefinitionsDBSyncer()

        self._insert_mock_roles()

        # Initial state, no roles
        user_db = UserDB(name='doesntexistwhaha')
        role_dbs = get_roles_for_user(user_db=user_db)
        self.assertItemsEqual(role_dbs, [])

        # Create mock remote role assignment
        role_db = self.roles['role_3']
        role_assignment_db = assign_role_to_user(role_db=role_db, user_db=user_db, is_remote=True)
        self.assertTrue(role_assignment_db.is_remote)

        # Verify assignment has been created
        role_dbs = get_roles_for_user(user_db=user_db)
        self.assertItemsEqual(role_dbs, [self.roles['role_3']])

        # Do the sync with two roles defined - verify remote role assignment hasn't been
        # manipulated with.
        api = UserRoleAssignmentFileFormatAPI(username=user_db.name,
                                              roles=['role_1', 'role_2'])
        syncer.sync_users_role_assignments(role_assignment_apis=[api])

        role_dbs = get_roles_for_user(user_db=user_db)
        self.assertEqual(len(role_dbs), 3)
        self.assertEqual(role_dbs[0], self.roles['role_1'])
        self.assertEqual(role_dbs[1], self.roles['role_2'])
        self.assertEqual(role_dbs[2], self.roles['role_3'])

        # Do sync with no roles - verify all roles except remote one are removed.
        api = UserRoleAssignmentFileFormatAPI(username=user_db.name,
                                              roles=[])
        syncer.sync_users_role_assignments(role_assignment_apis=[api])

        role_dbs = get_roles_for_user(user_db=user_db)
        self.assertEqual(len(role_dbs), 1)
        self.assertEqual(role_dbs[0], self.roles['role_3'])

    def assertRoleDBObjectExists(self, role_db):
        result = Role.get_by_id(str(role_db.id))
        self.assertTrue(result)
        self.assertEqual(role_db.id, result.id)

    def assertGrantDBObjectExists(self, permission_grant_id):
        result = PermissionGrant.get_by_id(str(permission_grant_id))
        self.assertTrue(result)
        self.assertEqual(permission_grant_id, str(result.id))

    def _insert_mock_roles(self):
        # Create some mock roles
        role_1_db = create_role(name='role_1')
        role_2_db = create_role(name='role_2')
        role_3_db = create_role(name='role_3')

        self.roles['role_1'] = role_1_db
        self.roles['role_2'] = role_2_db
        self.roles['role_3'] = role_3_db

        return self.roles


class RBACRemoteGroupToRoleSyncerTestCase(BaseRBACDefinitionsDBSyncerTestCase):
    def setUp(self):
        super(RBACRemoteGroupToRoleSyncerTestCase, self).setUp()

        self.roles = {}
        self.role_assignments = {}

        # Insert mock local role assignments
        role_db = create_role(name='mock_local_role_1')
        user_db = self.users['user_1']
        role_assignment_db_1 = assign_role_to_user(role_db=role_db, user_db=user_db,
                                                   is_remote=False)

        self.roles['mock_local_role_1'] = role_db
        self.role_assignments['assignment_1'] = role_assignment_db_1

        role_db = create_role(name='mock_local_role_2')
        user_db = self.users['user_1']
        role_assignment_db_2 = assign_role_to_user(role_db=role_db, user_db=user_db,
                                                   is_remote=False)

        self.roles['mock_local_role_2'] = role_db
        self.role_assignments['assignment_2'] = role_assignment_db_2

        role_db = create_role(name='mock_role_3')
        self.roles['mock_role_3'] = role_db

        role_db = create_role(name='mock_role_4')
        self.roles['mock_role_4'] = role_db

        role_db = create_role(name='mock_role_5')
        self.roles['mock_role_5'] = role_db

    def test_sync_no_groups_and_on_disk_definitions(self):
        syncer = RBACRemoteGroupToRoleSyncer()
        user_db = self.users['user_1']

        # Verify initial state
        role_dbs = get_roles_for_user(user_db=user_db, include_remote=True)
        self.assertEqual(len(role_dbs), 2)
        self.assertEqual(role_dbs[0], self.roles['mock_local_role_1'])
        self.assertEqual(role_dbs[1], self.roles['mock_local_role_2'])

        # No groups - should result in no new remote assignments but existing local assignments
        # shouldn't be manipulated
        result = syncer.sync(user_db=self.users['user_1'], groups=[])
        created_role_assignment_dbs = result[0]
        removed_role_assignment_dbs = result[1]
        self.assertEqual(created_role_assignment_dbs, [])
        self.assertEqual(removed_role_assignment_dbs, [])

        role_dbs = get_roles_for_user(user_db=user_db, include_remote=True)
        self.assertEqual(len(role_dbs), 2)
        self.assertEqual(role_dbs[0], self.roles['mock_local_role_1'])
        self.assertEqual(role_dbs[1], self.roles['mock_local_role_2'])

        # Groups but no mapping to role definitions, should result in no new remote assignments
        groups = ['CN=stormers,OU=groups,DC=stackstorm,DC=net']
        result = syncer.sync(user_db=self.users['user_1'], groups=groups)
        created_role_assignment_dbs = result[0]
        removed_role_assignment_dbs = result[1]
        self.assertEqual(created_role_assignment_dbs, [])
        self.assertEqual(removed_role_assignment_dbs, [])

        role_dbs = get_roles_for_user(user_db=user_db, include_remote=True)
        self.assertEqual(len(role_dbs), 2)
        self.assertEqual(role_dbs[0], self.roles['mock_local_role_1'])
        self.assertEqual(role_dbs[1], self.roles['mock_local_role_2'])

    def test_sync_success_no_existing_remote_assignments(self):
        syncer = RBACRemoteGroupToRoleSyncer()
        user_db = self.users['user_1']

        # Create mock mapping which maps CN=stormers,OU=groups,DC=stackstorm,DC=net
        # to "mock_role_3" and "mock_role_4"
        create_group_to_role_map(group='CN=stormers,OU=groups,DC=stackstorm,DC=net',
                                 roles=['mock_role_3', 'mock_role_4'])

        # Verify initial state
        role_dbs = get_roles_for_user(user_db=user_db, include_remote=True)
        self.assertEqual(len(role_dbs), 2)
        self.assertEqual(role_dbs[0], self.roles['mock_local_role_1'])

        groups = [
            'CN=stormers,OU=groups,DC=stackstorm,DC=net',
            'CN=testers,OU=groups,DC=stackstorm,DC=net',
            # We repeat the same group to validate that repated groups are correctly de-duplicated
            'CN=stormers,OU=groups,DC=stackstorm,DC=net',
        ]
        result = syncer.sync(user_db=self.users['user_1'], groups=groups)
        created_role_assignment_dbs = result[0]
        removed_role_assignment_dbs = result[1]
        self.assertEqual(len(created_role_assignment_dbs), 2)
        self.assertEqual(created_role_assignment_dbs[0].role, 'mock_role_3')
        self.assertEqual(created_role_assignment_dbs[1].role, 'mock_role_4')
        self.assertEqual(removed_role_assignment_dbs, [])

        # User should have two new roles assigned now
        role_dbs = get_roles_for_user(user_db=user_db, include_remote=True)
        self.assertEqual(len(role_dbs), 4)
        self.assertEqual(role_dbs[0], self.roles['mock_local_role_1'])
        self.assertEqual(role_dbs[1], self.roles['mock_local_role_2'])
        self.assertEqual(role_dbs[2], self.roles['mock_role_3'])
        self.assertEqual(role_dbs[3], self.roles['mock_role_4'])

    def test_sync_success_one_existing_remote_assignment(self):
        syncer = RBACRemoteGroupToRoleSyncer()
        user_db = self.users['user_1']

        # Create mock mapping which maps CN=stormers,OU=groups,DC=stackstorm,DC=net
        # to "mock_role_3" and "mock_role_4"
        create_group_to_role_map(group='CN=stormers,OU=groups,DC=stackstorm,DC=net',
                                 roles=['mock_role_3', 'mock_role_4'])

        # Assign existing remote mock_role_5 to the user
        role_db = self.roles['mock_role_5']
        assign_role_to_user(role_db=role_db, user_db=user_db, is_remote=True)

        # Verify initial state
        role_dbs = get_roles_for_user(user_db=user_db, include_remote=True)
        self.assertEqual(len(role_dbs), 3)
        self.assertEqual(role_dbs[0], self.roles['mock_local_role_1'])
        self.assertEqual(role_dbs[1], self.roles['mock_local_role_2'])
        self.assertEqual(role_dbs[2], self.roles['mock_role_5'])

        groups = [
            'CN=stormers,OU=groups,DC=stackstorm,DC=net',
            'CN=testers,OU=groups,DC=stackstorm,DC=net'
        ]
        result = syncer.sync(user_db=self.users['user_1'], groups=groups)
        created_role_assignment_dbs = result[0]
        removed_role_assignment_dbs = result[1]
        self.assertEqual(len(created_role_assignment_dbs), 2)
        self.assertEqual(created_role_assignment_dbs[0].role, 'mock_role_3')
        self.assertEqual(created_role_assignment_dbs[1].role, 'mock_role_4')
        self.assertEqual(len(removed_role_assignment_dbs), 1)
        self.assertEqual(removed_role_assignment_dbs[0].role, 'mock_role_5')

        # User should have two new roles assigned now, but the existing "mock_role_5" remote role
        # removed since it wasn't specified in any mapping
        role_dbs = get_roles_for_user(user_db=user_db, include_remote=True)
        self.assertEqual(len(role_dbs), 4)
        self.assertEqual(role_dbs[0], self.roles['mock_local_role_1'])
        self.assertEqual(role_dbs[1], self.roles['mock_local_role_2'])
        self.assertEqual(role_dbs[2], self.roles['mock_role_3'])
        self.assertEqual(role_dbs[3], self.roles['mock_role_4'])

    def test_sync_no_mappings_exist_for_the_provided_groups(self):
        syncer = RBACRemoteGroupToRoleSyncer()
        user_db = self.users['user_1']

        # Create mock mapping which maps CN=stormers,OU=groups,DC=stackstorm,DC=net
        # to "mock_role_3" and "mock_role_4"
        create_group_to_role_map(group='CN=stormers,OU=groups,DC=stackstorm,DC=net',
                                 roles=['mock_role_3', 'mock_role_4'])

        # Verify initial state
        role_dbs = get_roles_for_user(user_db=user_db, include_remote=True)
        self.assertEqual(len(role_dbs), 2)
        self.assertEqual(role_dbs[0], self.roles['mock_local_role_1'])
        self.assertEqual(role_dbs[1], self.roles['mock_local_role_2'])

        groups = [
            'CN=testers1,OU=groups,DC=stackstorm,DC=net',
            'CN=testers2,OU=groups,DC=stackstorm,DC=net'
        ]

        # No mappings exist for the groups user is a member of so no new assignments should be
        # created
        result = syncer.sync(user_db=self.users['user_1'], groups=groups)
        created_role_assignment_dbs = result[0]
        removed_role_assignment_dbs = result[1]
        self.assertEqual(created_role_assignment_dbs, [])
        self.assertEqual(removed_role_assignment_dbs, [])

    def test_sync_success_one_mapping_is_disabled_on_second_sync_run(self):
        syncer = RBACRemoteGroupToRoleSyncer()
        user_db = self.users['user_1']

        # Create mock mapping which maps CN=stormers,OU=groups,DC=stackstorm,DC=net
        # to "mock_role_3" and CN=testers,OU=groups,DC=stackstorm,DC=net to "mock_role_4"
        create_group_to_role_map(group='CN=stormers,OU=groups,DC=stackstorm,DC=net',
                                 roles=['mock_role_3'],
                                 enabled=True)
        create_group_to_role_map(group='CN=testers,OU=groups,DC=stackstorm,DC=net',
                                 roles=['mock_role_4'],
                                 enabled=True)

        # Verify initial state
        role_dbs = get_roles_for_user(user_db=user_db, include_remote=True)
        self.assertEqual(len(role_dbs), 2)
        self.assertEqual(role_dbs[0], self.roles['mock_local_role_1'])
        self.assertEqual(role_dbs[1], self.roles['mock_local_role_2'])

        groups = [
            'CN=stormers,OU=groups,DC=stackstorm,DC=net',
            'CN=testers,OU=groups,DC=stackstorm,DC=net'
        ]

        # Two new remote assignments should have been created
        # No mappings exist for the groups user is a member of so no new assignments should be
        # created
        result = syncer.sync(user_db=self.users['user_1'], groups=groups)
        created_role_assignment_dbs = result[0]
        removed_role_assignment_dbs = result[1]
        self.assertEqual(len(created_role_assignment_dbs), 2)
        self.assertEqual(created_role_assignment_dbs[0].role, 'mock_role_3')
        self.assertEqual(created_role_assignment_dbs[1].role, 'mock_role_4')
        self.assertEqual(removed_role_assignment_dbs, [])

        # Verify post sync run state - two new assignments should have been created
        role_dbs = get_roles_for_user(user_db=user_db, include_remote=True)
        self.assertEqual(len(role_dbs), 4)
        self.assertEqual(role_dbs[0], self.roles['mock_local_role_1'])
        self.assertEqual(role_dbs[1], self.roles['mock_local_role_2'])
        self.assertEqual(role_dbs[2], self.roles['mock_role_3'])
        self.assertEqual(role_dbs[3], self.roles['mock_role_4'])

        # Disable second mapping - one assignment should be removed
        mapping_db = GroupToRoleMapping.get(group='CN=testers,OU=groups,DC=stackstorm,DC=net')
        mapping_db.enabled = False
        GroupToRoleMapping.add_or_update(mapping_db)

        result = syncer.sync(user_db=self.users['user_1'], groups=groups)
        created_role_assignment_dbs = result[0]
        removed_role_assignment_dbs = result[1]
        self.assertEqual(len(created_role_assignment_dbs), 1)
        self.assertEqual(len(removed_role_assignment_dbs), 2)
        self.assertEqual(created_role_assignment_dbs[0].role, 'mock_role_3')
        self.assertEqual(removed_role_assignment_dbs[0].role, 'mock_role_3')
        self.assertEqual(removed_role_assignment_dbs[1].role, 'mock_role_4')

        # Verify post sync run state - mock_role_4 assignment should be removed
        role_dbs = get_roles_for_user(user_db=user_db, include_remote=True)
        self.assertEqual(len(role_dbs), 3)
        self.assertEqual(role_dbs[0], self.roles['mock_local_role_1'])
        self.assertEqual(role_dbs[1], self.roles['mock_local_role_2'])
        self.assertEqual(role_dbs[2], self.roles['mock_role_3'])
